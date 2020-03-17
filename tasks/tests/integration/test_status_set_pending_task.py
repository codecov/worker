import pytest

from database.tests.factories import CommitFactory, RepositoryFactory
from tasks.status_set_pending import StatusSetPendingTask
from torngit.status import Status


@pytest.mark.integration
class TestStatusSetPendingTask(object):
    @pytest.mark.asyncio
    async def test_set_pending(
        self, dbsession, mocker, mock_configuration, codecov_vcr, mock_redis
    ):
        repository = RepositoryFactory.create(
            owner__username="ThiagoCodecov",
            name="example-python",
            owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            yaml={"coverage": {"status": {"project": {"default": {"target": 100}}}}},
        )
        dbsession.add(repository)
        dbsession.flush()

        commit = CommitFactory.create(
            message="",
            branch="some-branch",
            commitid="b7acacdefaed67f5fba102d7001cc17539539e63",
            repository=repository,
        )
        dbsession.add(commit)

        mock_redis.sismember.side_effect = [True]

        task = StatusSetPendingTask()
        result = await task.run_async(
            dbsession, repository.repoid, commit.commitid, commit.branch, True
        )
        expected_result = {"status_set": True}
        assert result == expected_result
