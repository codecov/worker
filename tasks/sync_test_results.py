import logging

from django.db import connection
from shared.celery_config import sync_test_results_task_name
from shared.django_apps.reports.models import Test

from app import celery_app
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

# TODO: turn these into Django ORM calls

failure_rate_query = """
select 
    rti.test_id, 
    avg(
        case 
            when outcome = 'pass' then 0.0
            when outcome = 'failure' OR outcome = 'error' then 1.0
        end
    ) as failure_rate
from reports_testinstance rti
where rti.repoid = %s 
    and rti.created_at > current_date - interval '30 days' 
    and outcome != 'skip'
group by rti.test_id
"""


commit_agg_query = """
select 
    rti.test_id,
    array_agg(distinct commitid) as commits
from reports_testinstance rti
where 
    rti.repoid = %s 
    and rti.created_at > current_date - interval '30 days' 
    and (outcome = 'failure' or outcome = 'error')
group by rti.test_id
"""


class SyncTestResultsTask(BaseCodecovTask, name=sync_test_results_task_name):
    """
    This task refreshes the failure_rate and commits_where_fail fields on all Tests in a
    specified Repository
    """

    def run_impl(
        self,
        db_session,
        *,
        repoid,
        **kwargs,
    ):
        repoid = int(repoid)
        log.info(
            "Received sync test results task",
            extra=dict(repoid=repoid),
        )

        with connection.cursor() as cursor:
            cursor.execute(failure_rate_query, [repoid])
            rows = cursor.fetchall()
            failure_rate_dict = {row[0]: row[1] for row in rows}

            cursor.execute(commit_agg_query, [repoid])
            rows = cursor.fetchall()
            commit_agg_dict = {row[0]: row[1] for row in rows}

        tests = Test.objects.filter(repository_id=repoid).all()
        for test in tests:
            test.failure_rate = failure_rate_dict.get(test.id)
            commit_agg = commit_agg_dict.get(test.id)
            if commit_agg:
                test.commits_where_fail = list(commit_agg)

        Test.objects.bulk_update(tests, fields=["failure_rate", "commits_where_fail"])

        log.info("Done syncing test results info", extra=dict(repoid=repoid))

        return {"successful": True}


RegisteredSyncTestResultsTask = celery_app.register_task(SyncTestResultsTask())
sync_test_results_task = celery_app.tasks[RegisteredSyncTestResultsTask.name]
