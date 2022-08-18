import pytest

from database.models import MeasurementName
from database.tests.factories import RepositoryFactory
from database.tests.factories.core import CommitFactory
from database.tests.factories.timeseries import DatasetFactory
from tasks.timeseries_backfill import TimeseriesBackfillCommitsTask


@pytest.mark.asyncio
async def test_backfill_commits_run_async(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.timeseries_enabled", return_value=True)
    save_commit_measurements_mock = mocker.patch(
        "tasks.timeseries_backfill.save_commit_measurements"
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    commit1 = CommitFactory(repository=repository)
    dbsession.add(commit1)
    commit2 = CommitFactory(repository=repository)
    dbsession.add(commit2)

    dataset = DatasetFactory.create(
        name=MeasurementName.flag_coverage.value,
        repository_id=repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.flush()

    task = TimeseriesBackfillCommitsTask()
    res = await task.run_async(
        dbsession,
        commit_ids=[commit1.id_, commit2.id_],
        dataset_names=[dataset.name],
    )
    assert res == {"successful": True}

    assert save_commit_measurements_mock.call_count == 2
    assert save_commit_measurements_mock.called_with(commit1)
    assert save_commit_measurements_mock.called_with(commit2)


@pytest.mark.asyncio
async def test_backfill_commits_run_async_timeseries_not_enabled(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.timeseries_enabled", return_value=False)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    task = TimeseriesBackfillCommitsTask()
    res = await task.run_async(
        dbsession,
        commit_ids=[1, 2, 3],
        dataset_names=["testing"],
    )
    assert res == {"successful": False}

    assert not mock_group.called
