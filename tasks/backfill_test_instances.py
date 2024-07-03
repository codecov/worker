import logging

from django.db import transaction
from django.db.models import Q
from shared.django_apps.reports.models import TestInstance

from app import celery_app
from celery_config import backfill_test_instances_task_name
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class BackfillTestInstancesTask(
    BaseCodecovTask, name=backfill_test_instances_task_name
):
    def run_impl(
        self,
        *args,
        count=None,
        increment=1000,
        **kwargs,
    ):
        log.info(
            "Updating test instances",
        )

        test_instances_missing_info_count = TestInstance.objects.filter(
            Q(branch__isnull=True) | Q(commitid__isnull=True) | Q(repoid__isnull=True)
        ).count()

        if count is None:
            count = test_instances_missing_info_count
        else:
            count = min(count, test_instances_missing_info_count)

        log.info(f"Updating {count} test instances")

        for _ in range(0, count, increment):
            updates = []
            test_instances_missing_info = (
                TestInstance.objects.select_related("upload__report__commit")
                .filter(
                    (
                        Q(branch__isnull=True)
                        & Q(upload__report__commit__branch__isnull=False)
                    )
                    | Q(commitid__isnull=True)
                    | Q(repoid__isnull=True)
                )
                .order_by("id")[0:increment]
            )

            log.info("gathered test instances missing info")

            for test_instance in test_instances_missing_info:
                test_instance.branch = test_instance.upload.report.commit.branch
                test_instance.commitid = test_instance.upload.report.commit.commitid
                test_instance.repoid = test_instance.upload.report.commit.repository_id
                updates.append(test_instance)

            log.info("updated individual objects")

            TestInstance.objects.bulk_update(updates, ["branch", "commitid", "repoid"])

            log.info("bulk updated objects")

            transaction.commit()

            log.info("commited transaction")

        log.info(
            "Done updating test instances",
        )

        return {"successful": True}


RegisteredTrialExpirationCronTask = celery_app.register_task(
    BackfillTestInstancesTask()
)
backfill_test_instances_task = celery_app.tasks[BackfillTestInstancesTask.name]
