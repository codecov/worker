import logging

from django.db.models import Q
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

        test_instance_list = (
            TestInstance.objects.select_related("upload__report__commit")
            .filter(
                Q(branch__isnull=True)
                | Q(commitid__isnull=True)
                | Q(repoid__isnull=True)
            )
            .all()
        )

        for i in range(0, test_instance_list.count(), 1000):
            updates = []
            thing = (
                TestInstance.objects.select_related("upload__report__commit")
                .filter(
                    Q(branch__isnull=True)
                    | Q(commitid__isnull=True)
                    | Q(repoid__isnull=True)
                )
                .order_by("id")[0:1000]
            )
            for test_instance in thing:
                test_instance.branch = test_instance.upload.report.commit.branch
                test_instance.commitid = test_instance.upload.report.commit.commitid
                test_instance.repoid = test_instance.upload.report.commit.repository_id
                updates.append(test_instance)

            TestInstance.objects.bulk_update(updates, ["branch", "commitid", "repoid"])

        log.info(
            "Done updating test instances",
        )

        return {"successful": True}


RegisteredTrialExpirationCronTask = celery_app.register_task(
    BackfillTestInstancesTask()
)
backfill_test_instances_task = celery_app.tasks[BackfillTestInstancesTask.name]
