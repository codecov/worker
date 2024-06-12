import pytest
from shared.django_apps.reports.models import Test, TestInstance
from shared.django_apps.reports.tests.factories import RepositoryFactory, UploadFactory

from tasks.sync_test_results import SyncTestResultsTask


@pytest.fixture
def repo_fixture():
    return RepositoryFactory()


@pytest.fixture
def upload_fixture():
    return UploadFactory()


@pytest.fixture
def create_test_func(repo_fixture):
    test_i = 0

    def create_test():
        nonlocal test_i
        test_id = f"test_{test_i}"
        test = Test(
            id=test_id,
            repository=repo_fixture,
            testsuite="testsuite",
            name=f"test_{test_i}",
            flags_hash="",
        )
        test.save()
        test_i = test_i + 1

        return test

    return create_test


@pytest.fixture
def create_test_instance_func(repo_fixture, upload_fixture):
    def create_test_instance(test, outcome, commitid=""):
        ti = TestInstance(
            test=test,
            repoid=repo_fixture.repoid,
            outcome=outcome,
            upload=upload_fixture,
            duration_seconds=0,
            commitid=commitid,
        )
        ti.save()

    return create_test_instance


class TestSyncTestResults:
    def test_sync_test_results(
        self,
        transactional_db,
        repo_fixture,
        create_test_func,
        create_test_instance_func,
    ):
        test_1 = create_test_func()
        test_2 = create_test_func()

        create_test_instance_func(test_1, TestInstance.Outcome.FAILURE, "a")
        create_test_instance_func(test_1, TestInstance.Outcome.PASS, "b")
        create_test_instance_func(test_2, TestInstance.Outcome.SKIP, "c")
        create_test_instance_func(test_2, TestInstance.Outcome.ERROR, "d")
        create_test_instance_func(test_2, TestInstance.Outcome.PASS, "d")
        create_test_instance_func(test_2, TestInstance.Outcome.FAILURE, "d")

        _ = SyncTestResultsTask().run_impl(db_session=None, repoid=repo_fixture.repoid)

        test_1.refresh_from_db()
        test_2.refresh_from_db()

        assert test_1.failure_rate == 0.5
        assert test_1.commits_where_fail == ["a"]

        assert test_2.failure_rate == (2 / 3)
        assert test_2.commits_where_fail == ["d"]
