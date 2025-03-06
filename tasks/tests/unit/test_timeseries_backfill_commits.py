from shared.celery_config import timeseries_save_commit_measurements_task_name

from database.models import MeasurementName
from database.tests.factories import RepositoryFactory
from database.tests.factories.core import CommitFactory
from database.tests.factories.timeseries import DatasetFactory
from tasks.timeseries_backfill import TimeseriesBackfillCommitsTask


def test_backfill_commits_run_impl(dbsession, mocker):
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
    res = task.run_impl(
        dbsession,
        commit_ids=[commit1.id_, commit2.id_],
        dataset_names=[dataset.name],
    )
    assert res == {"successful": True}

    mocked_app.tasks[
        timeseries_save_commit_measurements_task_name
    ].apply_async.assert_any_call(
        kwargs={
            "commitid": commit1.commitid,
            "repoid": commit1.repoid,
            "dataset_names": [dataset.name],
        }
    )
    mocked_app.tasks[
        timeseries_save_commit_measurements_task_name
    ].apply_async.assert_any_call(
        kwargs={
            "commitid": commit2.commitid,
            "repoid": commit2.repoid,
            "dataset_names": [dataset.name],
        }
    )


def test_backfill_commits_run_impl_timeseries_not_enabled(dbsession, mocker):
    mocker.patch("tasks.timeseries_backfill.is_timeseries_enabled", return_value=False)
    mock_group = mocker.patch("tasks.timeseries_backfill.group")

    task = TimeseriesBackfillCommitsTask()
    res = task.run_impl(
        dbsession,
        commit_ids=[1, 2, 3],
        dataset_names=["testing"],
    )
    assert res == {"successful": False}

    assert not mock_group.called
