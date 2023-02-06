import pytest

from database.tests.factories import RepositoryFactory
from tasks.timeseries_delete import TimeseriesDeleteTask


@pytest.mark.asyncio
async def test_timeseries_delete_run_async(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.timeseries_enabled", return_value=True)
    delete_repository_data = mocker.patch(
        "tasks.timeseries_delete.delete_repository_data"
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    task = TimeseriesDeleteTask()
    res = await task.run_async(
        dbsession,
        repository_id=repository.repoid,
    )
    assert res == {"successful": True}

    delete_repository_data.assert_called_once_with(repository)


@pytest.mark.asyncio
async def test_timeseries_delete_run_async_invalid_repository(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.timeseries_enabled", return_value=True)

    task = TimeseriesDeleteTask()
    res = await task.run_async(
        dbsession,
        repository_id=9999,
    )
    assert res == {"successful": False}


@pytest.mark.asyncio
async def test_timeseries_delete_run_async_timeseries_not_enabled(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.timeseries_enabled", return_value=False)

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    task = TimeseriesDeleteTask()
    res = await task.run_async(
        dbsession,
        repository_id=repository.repoid,
    )
    assert res == {"successful": False}
