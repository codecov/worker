import pytest

from database.models import Measurement, MeasurementName
from database.tests.factories import CommitFactory, RepositoryFactory
from database.tests.factories.timeseries import DatasetFactory
from services.archive import ArchiveService
from tasks.timeseries_backfill import TimeseriesBackfillCommitsTask


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_dataset_run_async(dbsession, mocker, mock_storage):
    mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
    mocker.patch("tasks.timeseries_backfill.timeseries_enabled", return_value=True)

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
    res = await task.run_async(
        dbsession,
        commit_ids=[commit.id_],
        dataset_names=[
            MeasurementName.coverage.value,
            MeasurementName.flag_coverage.value,
        ],
    )
    assert res == {"successful": True}

    coverage_measurement = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.coverage.value,
            commit_sha=commit.commitid,
        )
        .one_or_none()
    )

    assert coverage_measurement
    assert coverage_measurement.value == 85.0

    flag_coverage_measurement = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.flag_coverage.value,
            commit_sha=commit.commitid,
        )
        .one_or_none()
    )

    assert flag_coverage_measurement
    assert flag_coverage_measurement.value == 85.0
