import pytest

from database.tests.factories import CommitFactory, RepositoryFactory
from tasks.status_set_pending import StatusSetPendingTask


@pytest.mark.integration
class TestStatusSetPendingTask(object):
    def test_set_pending(
        self, dbsession, mocker, mock_configuration, codecov_vcr, mock_redis
    ):
        repository = RepositoryFactory.create(
            owner__username="ThiagoCodecov",
            owner__service="github",
            name="example-python",
            owner__unencrypted_oauth_token="909b86f2e90668589666e2b5b76966797cee4b24",
            yaml={"coverage": {"status": {"project": {"default": {"target": 100}}}}},
        )
        dbsession.add(repository)
        dbsession.flush()

        commit = CommitFactory.create(
            message="",
            branch="some-branch",
            commitid="e3b6c976efe88b2a3781dc8157485e46bf2ac7ab",
            repository=repository,
        )
        dbsession.add(commit)

        mock_redis.sismember.side_effect = [True]

        task = StatusSetPendingTask()
        result = task.run_impl(
            dbsession, repository.repoid, commit.commitid, commit.branch, True
        )
        expected_result = {"status_set": True}
        assert result == expected_result
