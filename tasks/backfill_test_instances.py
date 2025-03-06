import logging

from shared.django_apps.reports.models import TestInstance

from app import celery_app
from celery_config import backfill_test_instances_task_name
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class BackfillTestInstancesTask(
    BaseCodecovTask, name=backfill_test_instances_task_name
):
    def run_impl(self, *args, dry_run=True, **kwargs):
        log.info(
            "Updating test instances",
        )

        test_instance_filter = TestInstance.objects.select_related(
            "upload__report__commit"
        ).filter(
            branch=None,
            commitid=None,
        )
        num_test_instances = test_instance_filter.count()
        all_test_instances = test_instance_filter.all()

        chunk_size = 1000

        chunks = [
            all_test_instances[i : i + chunk_size]
            for i in range(0, num_test_instances, chunk_size)
        ]

        for chunk in chunks:
            for test_instance in chunk:
                test_instance.branch = test_instance.upload.report.commit.branch
                test_instance.commitid = test_instance.upload.report.commit.commitid
            TestInstance.objects.bulk_update(chunk, ["branch", "commit"])

        log.info(
            "Done updating test instances",
        )

        return {"successful": True}


RegisteredTrialExpirationCronTask = celery_app.register_task(
    BackfillTestInstancesTask()
)
backfill_test_instances_task = celery_app.tasks[BackfillTestInstancesTask.name]
