from pathlib import Path

from sqlalchemy.exc import DBAPIError, InvalidRequestError
import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded
from celery.contrib.testing.mocks import TaskMessage

from tasks.base import BaseCodecovTask, BaseCodecovRequest


here = Path(__file__)


class SampleTask(BaseCodecovTask):
    name = "test.SampleTask"

    async def run_async(self, dbsession):
        return {"unusual": "return", "value": ["There"]}

    def write_to_db(self):
        return False


class SampleTaskWithError(BaseCodecovTask):
    async def run_async(self, dbsession):
        raise DBAPIError("statement", "params", "orig")

    def write_to_db(self):
        return False

    def retry(self):
        # Fake retry method
        raise Retry()


class SampleTaskWithSoftTimeout(BaseCodecovTask):
    async def run_async(self, dbsession):
        raise SoftTimeLimitExceeded()


class FailureSampleTask(BaseCodecovTask):

    name = "test.FailureSampleTask"

    async def run_async(self, *args, **kwargs):
        raise Exception("Whhhhyyyyyyy")


class RetrySampleTask(BaseCodecovTask):

    name = "test.RetrySampleTask"

    def run(self, *args, **kwargs):
        self.retry()


class TestBaseTask(object):
    def test_sample_run(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        result = SampleTask().run()
        assert result == {"unusual": "return", "value": ["There"]}

    def test_sample_run_db_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithError().run()

    def test_sample_run_softimeout(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(SoftTimeLimitExceeded):
            SampleTaskWithSoftTimeout().run()

    def test_wrap_up_dbsession_success(self, mocker):
        task = BaseCodecovTask()
        fake_session = mocker.MagicMock()
        task.wrap_up_dbsession(fake_session)
        assert fake_session.commit.call_count == 1
        assert fake_session.close.call_count == 1

    def test_wrap_up_dbsession_timeout_but_ok(self, mocker):
        task = BaseCodecovTask()
        fake_session = mocker.MagicMock(
            commit=mocker.MagicMock(side_effect=[SoftTimeLimitExceeded(), 1])
        )
        task.wrap_up_dbsession(fake_session)
        assert fake_session.commit.call_count == 2
        assert fake_session.close.call_count == 1

    def test_wrap_up_dbsession_timeout_nothing_works(self, mocker):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        task = BaseCodecovTask()
        fake_session = mocker.MagicMock(
            commit=mocker.MagicMock(
                side_effect=[SoftTimeLimitExceeded(), InvalidRequestError()]
            )
        )
        task.wrap_up_dbsession(fake_session)
        assert fake_session.commit.call_count == 2
        assert fake_session.close.call_count == 0
        assert mocked_get_db_session.remove.call_count == 1


class TestBaseCodecovTaskHooks(object):
    def test_sample_task_success(self, celery_app, mocker):

        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        DTask = celery_app.register_task(SampleTask())
        task = celery_app.tasks[DTask.name]
        k = task.apply()
        res = k.get()
        assert res == {"unusual": "return", "value": ["There"]}
        mock_metrics.assert_called_with("new-worker.task.test.SampleTask.successes")

    def test_sample_task_failure(self, celery_app, mocker):
        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        DTask = celery_app.register_task(FailureSampleTask())
        task = celery_app.tasks[DTask.name]
        with pytest.raises(Exception) as exc:
            task.apply().get()
        assert exc.value.args == ("Whhhhyyyyyyy",)
        mock_metrics.assert_called_with(
            "new-worker.task.test.FailureSampleTask.failures"
        )

    def test_sample_task_retry(self, celery_app, mocker):
        # Unfortunately we cant really call the task with apply().get()
        # Something happens inside celery as of version 4.3 that makes them
        #   not call on_Retry at all.
        # best we can do is to call on_retry ourselves and ensure this makes the
        # metric be called
        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        task = RetrySampleTask()
        task.on_retry("exc", "task_id", "args", "kwargs", "einfo")
        mock_metrics.assert_called_with("new-worker.task.test.RetrySampleTask.retries")


class TestBaseCodecovRequest(object):

    """
        All in all, this is a really weird class

        We are trying here to test some of the hooks celery providers for requests

        It's not easy to generate a situation where they can be called without intensely
            faking the situation

        If you every find a better way to test this, delete this class

        If things start going badly because of those tests, delete this class
    """

    def xRequest(self, mocker, name, celery_app):
        # I dont even know what I am doing here. Just trying to create a sample request Copied from
        # https://github.com/celery/celery/blob/4e4d308db88e60afeec97479a5a133671c671fce/t/unit/worker/test_request.py#L54
        id = None
        args = [1]
        kwargs = {"f": "x"}
        on_ack = mocker.Mock(name="on_ack")
        on_reject = mocker.Mock(name="on_reject")
        message = TaskMessage(name, id, args=args, kwargs=kwargs)
        return BaseCodecovRequest(
            message, app=celery_app, on_ack=on_ack, on_reject=on_reject
        )

    def test_sample_task_timeout(self, celery_app, mocker):
        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        DTask = celery_app.register_task(SampleTask())
        request = self.xRequest(mocker, DTask.name, celery_app)
        request.on_timeout(True, 10)
        mock_metrics.assert_called_with("new-worker.task.test.SampleTask.timeout")
