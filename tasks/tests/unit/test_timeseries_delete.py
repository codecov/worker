from database.models.timeseries import MeasurementName
from database.tests.factories import RepositoryFactory
from tasks.timeseries_delete import TimeseriesDeleteTask


def test_timeseries_delete_run_impl(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.is_timeseries_enabled", return_value=True)
    delete_repository_data = mocker.patch(
        "tasks.timeseries_delete.delete_repository_data"
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    task = TimeseriesDeleteTask()
    res = task.run_impl(
        dbsession,
        repository_id=repository.repoid,
    )
    assert res == {"successful": True}

    delete_repository_data.assert_called_once_with(repository)


def test_timeseries_delete_run_impl_invalid_repository(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.is_timeseries_enabled", return_value=True)

    task = TimeseriesDeleteTask()
    res = task.run_impl(
        dbsession,
        repository_id=9999,
    )
    assert res == {"successful": False, "reason": "Repository not found"}


def test_timeseries_delete_run_impl_timeseries_not_enabled(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.is_timeseries_enabled", return_value=False)

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    task = TimeseriesDeleteTask()
    res = task.run_impl(
        dbsession,
        repository_id=repository.repoid,
    )
    assert res == {"successful": False, "reason": "Timeseries not enabled"}


def test_timeseries_delete_measurements_only(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.is_timeseries_enabled", return_value=True)
    delete_repository_measurements = mocker.patch(
        "tasks.timeseries_delete.delete_repository_measurements"
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    task = TimeseriesDeleteTask()
    res = task.run_impl(
        dbsession,
        repository_id=repository.repoid,
        measurement_only=True,
        measurement_type=MeasurementName.coverage.value,
        measurement_id=f"{repository.repoid}",
    )
    assert res == {"successful": True}

    delete_repository_measurements.assert_called_once()


def test_timeseries_delete_measurements_only_unsuccessful(dbsession, mocker):
    mocker.patch("tasks.timeseries_delete.is_timeseries_enabled", return_value=True)
    delete_repository_measurements = mocker.patch(
        "tasks.timeseries_delete.delete_repository_measurements"
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    task = TimeseriesDeleteTask()
    res = task.run_impl(
        dbsession,
        repository_id=repository.repoid,
        measurement_only=True,
    )
    assert res == {
        "successful": False,
        "reason": "Measurement type and ID required to delete measurements only",
    }

    delete_repository_measurements.assert_not_called()
