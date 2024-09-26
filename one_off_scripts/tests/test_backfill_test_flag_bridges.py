import pytest
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.django_apps.reports.models import TestFlagBridge
from shared.django_apps.reports.tests.factories import (
    RepositoryFlagFactory,
    TestFactory,
    TestInstanceFactory,
    UploadFactory,
)

from one_off_scripts.backfill_test_flag_bridges import backfill_test_flag_bridges


@pytest.fixture
def setup_tests(transactional_db):
    repo = RepositoryFactory(test_analytics_enabled=True)

    flag_1 = RepositoryFlagFactory(repository=repo, flag_name="first")
    flag_2 = RepositoryFlagFactory(repository=repo, flag_name="second")
    flag_3 = RepositoryFlagFactory(repository=repo, flag_name="third")

    test_1 = TestFactory(repository_id=repo.repoid)
    upload_1 = UploadFactory()
    upload_1.flags.set([flag_1, flag_2])
    test_instance_1 = TestInstanceFactory(test=test_1, upload=upload_1)

    test_2 = TestFactory(repository_id=repo.repoid)
    upload_2 = UploadFactory()
    upload_2.flags.set([flag_3])
    test_instance_2 = TestInstanceFactory(test=test_2, upload=upload_2)


@pytest.mark.django_db(transaction=True)
def test_it_backfills_test_flag_bridges(setup_tests):
    bridges = TestFlagBridge.objects.all()
    assert len(bridges) == 0

    backfill_test_flag_bridges()

    bridges = TestFlagBridge.objects.all()
    assert len(bridges) == 3

    assert [(b.test.name, b.flag.flag_name) for b in bridges] == [
        (
            "test_1",
            "first",
        ),
        (
            "test_1",
            "second",
        ),
        (
            "test_2",
            "third",
        ),
    ]
