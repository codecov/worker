import pyarrow as pa
from django.db import connection
from shared.celery_config import cache_test_rollups_task_name
from shared.django_apps.core.models import Repository

from services.redis import get_redis_connection
from tasks.base import BaseCodecovTask


class CacheTestRollupsTask(BaseCodecovTask, name=cache_test_rollups_task_name):
    def run_impl(self, *, repoid, branch, **kwargs):
        repo = Repository.objects.get(repoid=repoid)
        default_branch = repo.branch

        if branch == default_branch:
            pin = True
        else:
            pin = False

        base_query = """
with
base_cte as (
	select rd.*
	from reports_dailytestrollups rd
	where
        rd.repoid = %(repoid)s
		and rd.date >= current_date - interval %(interval)s
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

        with connection.cursor() as cursor:
            for interval in [1, 7, 30]:
                cursor.execute(
                    base_query,
                    {
                        "repoid": repoid,
                        "branch": branch,
                        "interval": f"{interval} days",
                    },
                )
                aggregation_of_test_results = cursor.fetchall()
                data = map(list, zip(*aggregation_of_test_results))
                columns = {
                    column_name: column_values
                    for column_name, column_values in zip(
                        [col[0] for col in cursor.description],
                        data,
                    )
                }
                test_results_aggregate_schema = pa.schema(
                    [
                        pa.field("name", pa.string()),
                        pa.field("test_id", pa.string()),
                        pa.field("testsuite", pa.string()),
                        pa.field("flags", pa.list_(pa.string())),
                        pa.field("failure_rate", pa.float64()),
                        pa.field("flake_rate", pa.float64()),
                        pa.field("updated_at", pa.timestamp("s", tz="UTC")),
                        pa.field("avg_duration", pa.float64()),
                        pa.field("total_fail_count", pa.int64()),
                        pa.field("total_flaky_fail_count", pa.int64()),
                        pa.field("total_pass_count", pa.int64()),
                        pa.field("total_skip_count", pa.int64()),
                        pa.field("commits_where_fail", pa.int64()),
                        pa.field("last_duration", pa.float64()),
                    ],
                )
                table = pa.Table.from_pydict(
                    columns, schema=test_results_aggregate_schema
                )

                redis_key = f"ta:{repoid}:{branch}:{interval}"
                redis_connection = get_redis_connection()

                buf = pa.BufferOutputStream()
                with pa.ipc.new_file(buf, test_results_aggregate_schema) as writer:
                    writer.write_table(table)
                serialized_table = buf.getvalue().to_pybytes()

                if pin:
                    redis_connection.set(redis_key, serialized_table)
                else:
                    redis_connection.set(redis_key, serialized_table, ex=259200)

        return {"success": True}
