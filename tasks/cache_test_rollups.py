import datetime as dt

import polars as pl
from django.db import connection
from redis.exceptions import LockError
from shared.celery_config import cache_test_rollups_task_name

from app import celery_app
from services.redis import get_redis_connection
from services.storage import get_storage_client
from tasks.base import BaseCodecovTask


def get_query(with_end: bool) -> str:
    base_query = f"""
with
base_cte as (
	select rd.*
	from reports_dailytestrollups rd
	where
        rd.repoid = %(repoid)s
		and rd.date >= current_date - interval %(interval)s
        {"and rd.date < current_date - interval %(interval_end)s" if with_end else ""}
        and rd.branch = %(branch)s
),
failure_rate_cte as (
	select
		test_id,
		CASE
			WHEN SUM(pass_count) + SUM(fail_count) = 0 THEN 0
			ELSE SUM(fail_count)::float / (SUM(pass_count) + SUM(fail_count))
		END as failure_rate,
		CASE
			WHEN SUM(pass_count) + SUM(fail_count) = 0 THEN 0
			ELSE SUM(flaky_fail_count)::float / (SUM(pass_count) + SUM(fail_count))
		END as flake_rate,
		MAX(latest_run) as updated_at,
		AVG(avg_duration_seconds) AS avg_duration,
        SUM(fail_count) as total_fail_count,
        SUM(flaky_fail_count) as total_flaky_fail_count,
        SUM(pass_count) as total_pass_count,
        SUM(skip_count) as total_skip_count
	from base_cte
	group by test_id
),
commits_where_fail_cte as (
	select test_id, array_length((array_agg(distinct unnested_cwf)), 1) as failed_commits_count from (
		select test_id, commits_where_fail as cwf
		from base_cte
		where array_length(commits_where_fail,1) > 0
	) as tests_with_commits_that_failed, unnest(cwf) as unnested_cwf group by test_id
),
last_duration_cte as (
	select base_cte.test_id, last_duration_seconds from base_cte
	join (
		select
			test_id,
			max(created_at) as created_at
		from base_cte
		group by test_id
	) as latest_rollups
    on base_cte.created_at = latest_rollups.created_at and base_cte.test_id = latest_rollups.test_id
),
flags_cte as (
    select test_id, array_agg(distinct flag_name) as flags from reports_test_results_flag_bridge tfb
    join reports_test rt on rt.id = tfb.test_id
    join reports_repositoryflag rr on tfb.flag_id = rr.id
    where rt.repoid = %(repoid)s
    group by test_id
)


select
COALESCE(rt.computed_name, rt.name) as name,
rt.testsuite,
flags_cte.flags,
results.*
from
(
    select failure_rate_cte.*, coalesce(commits_where_fail_cte.failed_commits_count, 0) as commits_where_fail, last_duration_cte.last_duration_seconds as last_duration
    from failure_rate_cte
    full outer join commits_where_fail_cte using (test_id)
    full outer join last_duration_cte using (test_id)
) as results
join reports_test rt on results.test_id = rt.id
left join flags_cte using (test_id)
"""

    return base_query


class CacheTestRollupsTask(BaseCodecovTask, name=cache_test_rollups_task_name):
    def run_impl(self, _db_session, repoid: int, branch: str, **kwargs):
        redis_conn = get_redis_connection()
        try:
            with redis_conn.lock(
                f"rollups:{repoid}:{branch}", timeout=300, blocking_timeout=2
            ):
                self.run_impl_within_lock(repoid, branch)
                return {"success": True}
        except LockError:
            return {"in_progress": True}

    def run_impl_within_lock(self, repoid, branch):
        storage_service = get_storage_client()

        with connection.cursor() as cursor:
            for interval_start, interval_end in [
                (1, None),
                (7, None),
                (30, None),
                (2, 1),
                (14, 7),
                (60, 30),
            ]:
                base_query = get_query(with_end=interval_end is not None)
                query_params = {
                    "repoid": repoid,
                    "branch": branch,
                    "interval": f"{interval_start} days",
                }

                if interval_end is not None:
                    query_params["interval_end"] = f"{interval_end} days"

                cursor.execute(
                    base_query,
                    query_params,
                )
                aggregation_of_test_results = cursor.fetchall()

                df = pl.DataFrame(
                    aggregation_of_test_results,
                    [
                        "name",
                        "testsuite",
                        "flags",
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
                storage_key = (
                    f"test_results/rollups/{repoid}/{branch}/{interval_start}"
                    if interval_end is None
                    else f"test_results/rollups/{repoid}/{branch}/{interval_start}_{interval_end}"
                )

                serialized_table = df.write_ipc(None)
                serialized_table.seek(0)  # avoids Stream must be at beginning errors

                storage_service.write_file("codecov", storage_key, serialized_table)

        return


RegisteredCacheTestRollupTask = celery_app.register_task(CacheTestRollupsTask())
cache_test_rollups_task = celery_app.tasks[RegisteredCacheTestRollupTask.name]
