import logging

from django.db import transaction as django_transaction
from shared.django_apps.core.models import Repository
from shared.django_apps.reports.models import (
    RepositoryFlag,
    Test,
    TestFlagBridge,
    TestInstance,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger()


def backfill_test_flag_bridges(repoid=None):
    log.info("Backfilling TestFlagBridge objects", extra=dict(repoid=repoid))
    repos = Repository.objects.filter(test_analytics_enabled=True)
    if repoid is not None:
        repos = repos.filter(repoid=repoid)

    for repo in repos:
        tests = Test.objects.filter(repository_id=repo.repoid)

        flags = {
            flag.flag_name: flag
            for flag in RepositoryFlag.objects.filter(repository=repo)
        }

        bridges_to_create = []
        for test in tests:
            TestFlagBridge.objects.filter(test=test).delete()

            first_test_instance = (
                TestInstance.objects.filter(test_id=test.id)
                .select_related("upload")
                .first()
            )

            if first_test_instance is None:
                continue

            flag_names = first_test_instance.upload.flag_names

            for flag_name in flag_names:
                new_bridge = TestFlagBridge(test=test, flag=flags[flag_name])
                bridges_to_create.append(new_bridge)

        TestFlagBridge.objects.bulk_create(bridges_to_create, 1000)
        log.info(
            "Done creating flag bridges for repo",
            extra=dict(repoid=repoid, num_tests=len(tests)),
        )
        django_transaction.commit()
