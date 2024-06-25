from shared.django_apps.reports.models import TestInstance

from tasks.backfill_test_instances import BackfillTestInstancesTask


class TestBackfillTestInstancesTask:
    def test_backfill_test_instances_task(
        self,
        transactional_db,
        repo_fixture,
        create_test_func,
        create_test_instance_func,
        create_upload_func,
    ):
        test = create_test_func()

        test_instances = [
            create_test_instance_func(
                test, TestInstance.Outcome.ERROR, upload=create_upload_func()
            )
            for i in range(0, 1001)
        ]

        BackfillTestInstancesTask().run_impl()

        for test_instance in test_instances:
            test_instance.refresh_from_db()
            assert test_instance.branch == test_instance.upload.report.commit.branch
            assert test_instance.commitid == test_instance.upload.report.commit.commitid
            assert (
                test_instance.repoid == test_instance.upload.report.commit.repository_id
            )
