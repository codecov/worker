from shared.django_apps.reports.models import TestInstance

from tasks.sync_test_results import SyncTestResultsTask


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
        create_test_instance_func(test_2, TestInstance.Outcome.FAILURE, "d")
        create_test_instance_func(test_2, TestInstance.Outcome.ERROR, "e")

        _ = SyncTestResultsTask().run_impl(db_session=None, repoid=repo_fixture.repoid)

        test_1.refresh_from_db()
        test_2.refresh_from_db()

        assert test_1.failure_rate == 0.5
        assert test_1.commits_where_fail == ["a"]

        assert test_2.failure_rate == (4 / 5)
        assert test_2.commits_where_fail == ["d", "e"]
