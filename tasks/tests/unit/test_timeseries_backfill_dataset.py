from datetime import datetime

from database.models import MeasurementName
from database.tests.factories import RepositoryFactory
from database.tests.factories.core import CommitFactory
from database.tests.factories.timeseries import DatasetFactory
from tasks.timeseries_backfill import (
    TimeseriesBackfillDatasetTask,
    timeseries_backfill_commits_task,
)


def test_backfill_dataset_run_impl(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=True)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    commit1 = CommitFactory(
        repository=repository, timestamp=datetime(2022, 1, 1, 0, 0, 0)
    )
    dbsession.add(commit1)
    commit2 = CommitFactory(
        repository=repository, timestamp=datetime(2022, 2, 1, 0, 0, 0)
    )
    dbsession.add(commit2)
    commit3 = CommitFactory(
        repository=repository, timestamp=datetime(2022, 3, 1, 0, 0, 0)
    )
    dbsession.add(commit3)
    commit4 = CommitFactory(
        repository=repository, timestamp=datetime(2022, 4, 1, 0, 0, 0)
    )
    dbsession.add(commit4)

    dataset = DatasetFactory.create(
        name=MeasurementName.flag_coverage.value,
        repository_id=repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.flush()

    task = TimeseriesBackfillDatasetTask()
    res = task.run_impl(
        dbsession,
        dataset_id=dataset.id_,
        start_date="2022-01-01T00:00:00",
        end_date="2022-03-15T00:00:00",
        batch_size=2,
    )
    assert res == {"successful": True}

    expected_signatures = [
        timeseries_backfill_commits_task.signature(
            kwargs=dict(
                commit_ids=[commit3.id_, commit2.id_],
                dataset_names=[dataset.name],
            ),
        ),
        timeseries_backfill_commits_task.signature(
            kwargs=dict(
                commit_ids=[commit1.id_],
                dataset_names=[dataset.name],
            ),
        ),
    ]
    mock_group.assert_called_once_with(expected_signatures)


def test_backfill_dataset_run_impl_invalid_dataset(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=True)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    dataset = DatasetFactory.create(
        name=MeasurementName.flag_coverage.value,
        repository_id=repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.flush()

    task = TimeseriesBackfillDatasetTask()
    res = task.run_impl(
        dbsession,
        dataset_id=9999,
        start_date="2022-01-01T00:00:00",
        end_date="2022-12-31T00:00:00",
    )
    assert res == {"successful": False}

    assert not mock_group.called


def test_backfill_dataset_run_impl_invalid_repository(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=True)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    dataset = DatasetFactory.create(
        name=MeasurementName.flag_coverage.value,
        repository_id=9999,
    )
    dbsession.add(dataset)
    dbsession.flush()

    task = TimeseriesBackfillDatasetTask()
    res = task.run_impl(
        dbsession,
        dataset_id=dataset.id_,
        start_date="2022-01-01T00:00:00",
        end_date="2022-12-31T00:00:00",
    )
    assert res == {"successful": False}

    assert not mock_group.called


def test_backfill_dataset_run_impl_invalid_start_date(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=True)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    dataset = DatasetFactory.create(
        name=MeasurementName.flag_coverage.value,
        repository_id=repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.flush()

    task = TimeseriesBackfillDatasetTask()
    res = task.run_impl(
        dbsession,
        dataset_id=dataset.id_,
        start_date="invalid",
        end_date="2022-12-31T00:00:00",
    )
    assert res == {"successful": False}

    assert not mock_group.called


def test_backfill_dataset_run_impl_invalid_end_date(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=True)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    dataset = DatasetFactory.create(
        name=MeasurementName.flag_coverage.value,
        repository_id=repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.flush()

    task = TimeseriesBackfillDatasetTask()
    res = task.run_impl(
        dbsession,
        dataset_id=dataset.id_,
        start_date="2022-01-01T00:00:00",
        end_date="invalid",
    )
    assert res == {"successful": False}

    assert not mock_group.called


def test_backfill_dataset_run_impl_timeseries_not_enabled(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=False)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    task = TimeseriesBackfillDatasetTask()
    res = task.run_impl(
        dbsession,
        dataset_id=9999,
        start_date="2022-01-01T00:00:00",
        end_date="2022-12-31T00:00:00",
    )
    assert res == {"successful": False}

    assert not mock_group.called
