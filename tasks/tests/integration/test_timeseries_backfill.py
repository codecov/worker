import pytest
from shared.celery_config import timeseries_save_commit_measurements_task_name

from database.models import MeasurementName
from database.tests.factories import CommitFactory, RepositoryFactory
from database.tests.factories.timeseries import DatasetFactory
from services.archive import ArchiveService
from tasks.timeseries_backfill import TimeseriesBackfillCommitsTask


@pytest.mark.integration
def test_backfill_dataset_run_impl(dbsession, mocker, mock_storage):
    mocker.patch("services.timeseries.is_timeseries_enabled", return_value=True)
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=True)
    mocked_app = mocker.patch.object(
        TimeseriesBackfillCommitsTask,
        "app",
        tasks={
            timeseries_save_commit_measurements_task_name: mocker.MagicMock(),
        },
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    coverage_dataset = DatasetFactory.create(
        name=MeasurementName.coverage.value, repository_id=repository.repoid
    )
    dbsession.add(coverage_dataset)
    flag_coverage_dataset = DatasetFactory.create(
        name=MeasurementName.flag_coverage.value, repository_id=repository.repoid
    )
    dbsession.add(flag_coverage_dataset)
    dbsession.flush()

    commit = CommitFactory.create(
        repository=repository,
    )
    dbsession.add(commit)
    dbsession.flush()

    with open("tasks/tests/samples/sample_chunks_1.txt") as f:
        content = f.read().encode()
        archive_hash = ArchiveService.get_archive_hash(commit.repository)
        chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
        mock_storage.write_file("archive", chunks_url, content)
        master_chunks_url = (
            f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
        )
        mock_storage.write_file("archive", master_chunks_url, content)

    task = TimeseriesBackfillCommitsTask()
    dataset_names = [
        MeasurementName.coverage.value,
        MeasurementName.flag_coverage.value,
    ]
    res = task.run_impl(
        dbsession,
        commit_ids=[commit.id_],
        dataset_names=dataset_names,
    )
    assert res == {"successful": True}
    mocked_app.tasks[
        timeseries_save_commit_measurements_task_name
    ].apply_async.assert_called_once_with(
        kwargs={
            "commitid": commit.commitid,
            "repoid": commit.repoid,
            "dataset_names": dataset_names,
        }
    )
