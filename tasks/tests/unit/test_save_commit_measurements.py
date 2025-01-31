from database.tests.factories.core import CommitFactory, OwnerFactory, RepositoryFactory
from services.timeseries import MeasurementName
from tasks.save_commit_measurements import SaveCommitMeasurementsTask


class TestSaveCommitMeasurements(object):
    def test_save_commit_measurements_success(self, dbsession, mocker):
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
        assert task.run_impl(
            dbsession,
            commitid=commit.commitid,
            repoid=commit.repoid,
            dataset_names=[
                MeasurementName.coverage.value,
                MeasurementName.flag_coverage.value,
            ],
        ) == {"successful": True}
        save_commit_measurements_mock.assert_called_with(
            commit=commit,
            dataset_names=[
                MeasurementName.coverage.value,
                MeasurementName.flag_coverage.value,
            ],
        )

    def test_save_commit_measurements_no_commit(self, dbsession):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()

        task = SaveCommitMeasurementsTask()
        assert task.run_impl(
            dbsession, commitid="123asdf", repoid=123, dataset_names=[]
        ) == {
            "successful": False,
            "error": "no_commit_in_db",
        }

    def test_save_commit_measurements_exception(self, mocker, dbsession):
        save_commit_measurements_mock = mocker.patch(
            "tasks.save_commit_measurements.save_commit_measurements"
        )
        save_commit_measurements_mock.side_effect = Exception("Muy malo")
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
        assert task.run_impl(
            dbsession,
            commitid=commit.commitid,
            repoid=commit.repoid,
            dataset_names=[
                MeasurementName.coverage.value,
                MeasurementName.flag_coverage.value,
            ],
        ) == {
            "successful": False,
            "error": "exception",
        }
