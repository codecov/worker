from datetime import datetime, timezone
from time import time

import pytest

from database.tests.factories import RepositoryFactory
from tasks.timeseries_backfill import TimeseriesBackfillTask


@pytest.mark.asyncio
async def test_backfill_run_async(dbsession, mocker):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    save_repository_measurements = mocker.patch(
        "tasks.timeseries_backfill.save_repository_measurements"
    )

    task = TimeseriesBackfillTask()
    start_date = "2022-06-01T00:00:00+0000"
    end_date = "2022-06-30T00:00:00+0000"
    res = await task.run_async(
        dbsession, repoid=repository.repoid, start_date=start_date, end_date=end_date
    )
    assert res == {"successful": True}

    save_repository_measurements.assert_called_once_with(
        repository,
        datetime(2022, 6, 1, 0, 0, 0).replace(tzinfo=timezone.utc),
        datetime(2022, 6, 30, 0, 0, 0).replace(tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_backfill_run_async_invalid_repo(dbsession, mocker):
    save_repository_measurements = mocker.patch(
        "tasks.timeseries_backfill.save_repository_measurements"
    )

    task = TimeseriesBackfillTask()
    start_date = "2022-06-01T00:00:00+0000"
    end_date = "wrong"
    res = await task.run_async(
        dbsession, repoid=9999, start_date=start_date, end_date=end_date
    )
    assert res == {"successful": False}

    assert not save_repository_measurements.called


@pytest.mark.asyncio
async def test_backfill_run_async_invalid_start_date(dbsession, mocker):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    save_repository_measurements = mocker.patch(
        "tasks.timeseries_backfill.save_repository_measurements"
    )

    task = TimeseriesBackfillTask()
    start_date = "wrong"
    end_date = "2022-06-30T00:00:00+0000"
    res = await task.run_async(
        dbsession, repoid=repository.repoid, start_date=start_date, end_date=end_date
    )
    assert res == {"successful": False}

    assert not save_repository_measurements.called


@pytest.mark.asyncio
async def test_backfill_run_async_invalid_end_date(dbsession, mocker):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    save_repository_measurements = mocker.patch(
        "tasks.timeseries_backfill.save_repository_measurements"
    )

    task = TimeseriesBackfillTask()
    start_date = "2022-06-01T00:00:00+0000"
    end_date = "wrong"
    res = await task.run_async(
        dbsession, repoid=repository.repoid, start_date=start_date, end_date=end_date
    )
    assert res == {"successful": False}

    assert not save_repository_measurements.called
