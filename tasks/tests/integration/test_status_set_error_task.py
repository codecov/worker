import pytest

from database.tests.factories import CommitFactory, RepositoryFactory
from tasks.status_set_error import StatusSetErrorTask
from torngit.status import Status


@pytest.mark.integration
class TestStatusSetErrorTask(object):
    @pytest.mark.asyncio
    async def test_set_error(self, dbsession, mocker, mock_configuration, codecov_vcr):
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
            branch="thiago/test-1",
            commitid="c2a05aa15ecad5bec37e29b9fe51ef30120f8642",
            repository=repository,
        )
        dbsession.add(commit)

        task = StatusSetErrorTask()
        result = await task.run_async(
            dbsession, repository.repoid, commit.commitid, message="Test err message"
        )
        expected_result = {"status_set": True}
        assert result == expected_result
