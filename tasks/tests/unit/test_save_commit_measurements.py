import pytest

from database.tests.factories.core import CommitFactory, OwnerFactory, RepositoryFactory
from tasks.save_commit_measurements import SaveCommitMeasurementsTask


class TestSaveCommitMeasurements(object):
    @pytest.mark.asyncio
    async def test_save_commit_measurements_success(self, dbsession, mocker):
        save_commit_measurements_mock = mocker.patch(
            "tasks.save_commit_measurements.save_commit_measurements"
        )
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)

        repository = RepositoryFactory.create(
            owner=owner, languages_last_updated=None, languages=[]
        )
        dbsession.add(repository)

        commit = CommitFactory.create(repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        task = SaveCommitMeasurementsTask()
        assert await task.run_async(
            dbsession, commitid=commit.commitid, repoid=commit.repoid
        ) == {"successful": True}
        assert save_commit_measurements_mock.called_with(
            commitid=commit.commitid, dataset_names=None
        )

    @pytest.mark.asyncio
    async def test_save_commit_measurements_no_commit(self, dbsession):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()

        task = SaveCommitMeasurementsTask()
        assert await task.run_async(
            dbsession, commitid="123asdf", repoid=123, dataset_names=[]
        ) == {
            "successful": False,
            "error": "no_commit_in_db",
        }
