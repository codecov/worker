import pytest
from celery.exceptions import Retry

from database.models.core import Pull
from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from database.tests.factories.core import UploadFactory
from tasks.upload_completion import CompleteUploadTask


class TestUploadCompletionTask(object):
    @pytest.mark.asyncio
    async def test_upload_completion(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_storage,
        mock_redis,
        celery_app,
    ):

        mocked_app = mocker.patch.object(
            CompleteUploadTask,
            "app",
            tasks={
                "app.tasks.notify.Notify": mocker.MagicMock(),
                "app.tasks.pulls.Sync": mocker.MagicMock(),
                "app.tasks.compute_comparison.ComputeComparison": mocker.MagicMock(),
            },
        )

        commit = CommitFactory.create(pullid=10)
        pull = PullFactory.create(
            repository=commit.repository, head=commit.commitid, pullid=commit.pullid
        )
        upload = UploadFactory.create(report__commit=commit)
        compared_to = CommitFactory.create(repository=commit.repository)
        pull.compared_to = compared_to.commitid
        dbsession.add(commit)
        dbsession.add(upload)
        dbsession.add(pull)
        dbsession.add(compared_to)
        dbsession.flush()
        result = await CompleteUploadTask().run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            report_code=None,
            current_yaml={},
        )
        assert {"notifications_called": True} == result
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_called_with(
            kwargs=dict(
                commitid=commit.commitid, current_yaml=None, repoid=commit.repoid
            )
        )
        mocked_app.tasks["app.tasks.pulls.Sync"].apply_async.assert_called_with(
            kwargs={
                "pullid": commit.pullid,
                "repoid": commit.repoid,
                "should_send_notifications": False,
            }
        )
        assert mocked_app.send_task.call_count == 0

        mocked_app.tasks[
            "app.tasks.compute_comparison.ComputeComparison"
        ].apply_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_completion_uploads_still_processing(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_storage,
        mock_redis,
        celery_app,
    ):

        mocker.patch.object(
            CompleteUploadTask,
            "app",
            celery_app,
        )
        commit = CommitFactory.create()
        upload = UploadFactory.create(report__commit=commit, state="")
        dbsession.add(commit)
        dbsession.add(upload)
        dbsession.flush()
        with pytest.raises(Retry):
            result = await CompleteUploadTask().run_async(
                dbsession,
                repoid=commit.repoid,
                commitid=commit.commitid,
                report_code=None,
                current_yaml={},
            )
            assert {"notifications_called": False} == result
