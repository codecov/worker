import datetime as dt
from typing import Literal

import polars as pl
import shared.storage
from django.db import connections
from redis.exceptions import LockError
from shared.celery_config import cache_test_rollups_task_name
from shared.config import get_config
from shared.django_apps.reports.models import LastCacheRollupDate

from app import celery_app
from django_scaffold import settings
from services.redis import get_redis_connection
from services.test_analytics.ta_cache_rollups import cache_rollups
from tasks.base import BaseCodecovTask

# Reminder: `a BETWEEN x AND y` is equivalent to `a >= x AND a <= y`
# Since we are working with calendar days, using a range of `0..0` gives us *today*,
# and a range of `1..1` gives use *yesterday*.
BASE_SUBQUERY = """
SELECT *
FROM reports_dailytestrollups
WHERE repoid = %(repoid)s
  AND branch = %(branch)s
  AND date BETWEEN
    (CURRENT_DATE - INTERVAL %(interval_start)s) AND
    (CURRENT_DATE - INTERVAL %(interval_end)s)
"""

TEST_AGGREGATION_SUBQUERY = """
SELECT test_id,
       CASE
           WHEN SUM(pass_count) + SUM(fail_count) = 0 THEN 0
           ELSE SUM(fail_count)::float / (SUM(pass_count) + SUM(fail_count))
       END AS failure_rate,
       CASE
           WHEN SUM(pass_count) + SUM(fail_count) = 0 THEN 0
           ELSE SUM(flaky_fail_count)::float / (SUM(pass_count) + SUM(fail_count))
       END AS flake_rate,
       MAX(latest_run) AS updated_at,
       AVG(avg_duration_seconds) AS avg_duration,
       SUM(fail_count) AS total_fail_count,
       SUM(flaky_fail_count) AS total_flaky_fail_count,
       SUM(pass_count) AS total_pass_count,
       SUM(skip_count) AS total_skip_count
FROM base_cte
GROUP BY test_id
"""

COMMITS_FAILED_SUBQUERY = """
SELECT test_id,
       array_length((array_agg(DISTINCT unnested_cwf)), 1) AS failed_commits_count
FROM
  (SELECT test_id,
          commits_where_fail AS cwf
   FROM base_cte
   WHERE array_length(commits_where_fail, 1) > 0) AS tests_with_commits_that_failed,
     unnest(cwf) AS unnested_cwf
GROUP BY test_id
"""

LAST_DURATION_SUBQUERY = """
SELECT base_cte.test_id,
       last_duration_seconds
FROM base_cte
JOIN
  (SELECT test_id,
          max(created_at) AS created_at
   FROM base_cte
   GROUP BY test_id) AS latest_rollups ON base_cte.created_at = latest_rollups.created_at
AND base_cte.test_id = latest_rollups.test_id
"""

TEST_FLAGS_SUBQUERY = """
SELECT test_id,
       array_agg(DISTINCT flag_name) AS flags
FROM reports_test_results_flag_bridge tfb
JOIN reports_test rt ON rt.id = tfb.test_id
JOIN reports_repositoryflag rr ON tfb.flag_id = rr.id
WHERE rt.repoid = %(repoid)s
GROUP BY test_id
"""

ROLLUP_QUERY = f"""
WITH
  base_cte AS ({BASE_SUBQUERY}),
  failure_rate_cte AS ({TEST_AGGREGATION_SUBQUERY}),
  commits_where_fail_cte AS ({COMMITS_FAILED_SUBQUERY}),
  last_duration_cte AS ({LAST_DURATION_SUBQUERY}),
  flags_cte AS ({TEST_FLAGS_SUBQUERY})

SELECT COALESCE(rt.computed_name, rt.name) AS name,
       rt.testsuite,
       flags_cte.flags,
       results.*
FROM
  (SELECT failure_rate_cte.*,
          coalesce(commits_where_fail_cte.failed_commits_count, 0) AS commits_where_fail,
          last_duration_cte.last_duration_seconds AS last_duration
   FROM failure_rate_cte
   FULL OUTER JOIN commits_where_fail_cte USING (test_id)
   FULL OUTER JOIN last_duration_cte USING (test_id)) AS results
JOIN reports_test rt ON results.test_id = rt.id
LEFT JOIN flags_cte USING (test_id)
"""


class CacheTestRollupsTask(BaseCodecovTask, name=cache_test_rollups_task_name):
    def run_impl(
        self,
        _db_session,
        repoid: int,
        branch: str,
        update_date: bool = True,
        impl_type: Literal["old", "new", "both"] = "old",
        **kwargs,
    ):
        redis_conn = get_redis_connection()
        try:
            with redis_conn.lock(
                f"rollups:{repoid}:{branch}", timeout=300, blocking_timeout=2
            ):
                if impl_type == "new" or impl_type == "both":
                    cache_rollups(repoid, branch)
                    cache_rollups(repoid, None)
                    if impl_type == "new":
                        return {"success": True}

                self.run_impl_within_lock(repoid, branch)

                if update_date:
                    LastCacheRollupDate.objects.update_or_create(
                        repository_id=repoid,
                        branch=branch,
                        defaults={"last_rollup_date": dt.date.today()},
                    )
                return {"success": True}
        except LockError:
            return {"in_progress": True}

    def run_impl_within_lock(self, repoid: int, branch: str):
        storage_service = shared.storage.get_appropriate_storage_service(repoid)

        if get_config("setup", "database", "read_replica_enabled", default=False):
            connection = connections["default_read"]
        else:
            connection = connections["default"]

        with connection.cursor() as cursor:
            for interval_start, interval_end in [
                # NOTE: working with calendar days and intervals,
                # `(CURRENT_DATE - INTERVAL '1 days')` means *yesterday*,
                # and `2..1` matches *the day before yesterday*.
                (1, None),
                (2, 1),
                (7, None),
                (14, 7),
                (30, None),
                (60, 30),
            ]:
                query_params = {
                    "repoid": repoid,
                    "branch": branch,
                    "interval_start": f"{interval_start} days",
                    # SQL `BETWEEN` syntax is equivalent to `<= end`, with an inclusive end date,
                    # thats why we do a `+1` here:
                    "interval_end": f"{interval_end + 1 if interval_end else 0} days",
                }

                cursor.execute(ROLLUP_QUERY, query_params)
                aggregation_of_test_results = cursor.fetchall()

                df = pl.DataFrame(
                    aggregation_of_test_results,
                    [
                        "name",
                        "testsuite",
                        ("flags", pl.List(pl.String)),
                        "test_id",
                        "failure_rate",
                        "flake_rate",
                        ("updated_at", pl.Datetime(time_zone=dt.UTC)),
                        "avg_duration",
                        "total_fail_count",
                        "total_flaky_fail_count",
                        "total_pass_count",
                        "total_skip_count",
                        "commits_where_fail",
                        "last_duration",
                    ],
                    orient="row",
                )

                serialized_table = df.write_ipc(None)
                serialized_table.seek(0)  # avoids Stream must be at beginning errors

                storage_key = (
                    f"test_results/rollups/{repoid}/{branch}/{interval_start}"
                    if interval_end is None
                    else f"test_results/rollups/{repoid}/{branch}/{interval_start}_{interval_end}"
                )
                storage_service.write_file(
                    settings.GCS_BUCKET_NAME, storage_key, serialized_table
                )


RegisteredCacheTestRollupTask = celery_app.register_task(CacheTestRollupsTask())
cache_test_rollups_task = celery_app.tasks[RegisteredCacheTestRollupTask.name]
