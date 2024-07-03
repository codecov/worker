import datetime as dt
import logging

from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Avg, Case, FloatField, Value, When
from shared.celery_config import sync_test_results_task_name
from shared.django_apps.reports.models import Test, TestInstance

from app import celery_app
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


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

        thirty_days_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=30)

        failure_rates_queryset = (
            TestInstance.objects.filter(
                repoid=repoid,
                created_at__gt=thirty_days_ago,
                outcome__in=["pass", "failure", "error"],
            )
            .values("test_id")
            .annotate(
                failure_rate=Avg(
                    Case(
                        When(outcome="pass", then=Value(0.0)),
                        When(outcome__in=["failure", "error"], then=Value(1.0)),
                        output_field=FloatField(),
                    )
                )
            )
        )

        failure_rate_dict = {
            obj["test_id"]: obj["failure_rate"] for obj in failure_rates_queryset
        }

        commit_agg_queryset = (
            TestInstance.objects.filter(
                repoid=repoid,
                created_at__gt=thirty_days_ago,
                outcome__in=["failure", "error"],
            )
            .values("test_id")
            .annotate(commits=ArrayAgg("commitid", distinct=True))
        )

        commit_agg_dict = {
            obj["test_id"]: obj["commits"] for obj in commit_agg_queryset
        }

        tests = Test.objects.filter(repository_id=repoid).all()
        for test in tests:
            test.failure_rate = failure_rate_dict.get(test.id)
            commit_agg = commit_agg_dict.get(test.id)
            if commit_agg:
                test.commits_where_fail = list(commit_agg)
            else:
                test.commits_where_fail = None

        Test.objects.bulk_update(tests, fields=["failure_rate", "commits_where_fail"])

        log.info("Done syncing test results info", extra=dict(repoid=repoid))

        return {"successful": True}


RegisteredSyncTestResultsTask = celery_app.register_task(SyncTestResultsTask())
sync_test_results_task = celery_app.tasks[RegisteredSyncTestResultsTask.name]
