from pathlib import Path

import psycopg2
import pytest
from celery import chain
from celery.contrib.testing.mocks import TaskMessage
from celery.exceptions import Retry, SoftTimeLimitExceeded
from shared.billing import BillingPlan
from shared.celery_config import sync_repos_task_name, upload_task_name
from sqlalchemy.exc import DBAPIError, IntegrityError, InvalidRequestError

from database.tests.factories.core import OwnerFactory, RepositoryFactory
from tasks.base import BaseCodecovRequest, BaseCodecovTask
from tasks.base import celery_app as base_celery_app

here = Path(__file__)


class SampleTask(BaseCodecovTask):
    name = "test.SampleTask"

    async def run_async(self, dbsession):
        return {"unusual": "return", "value": ["There"]}


class SampleTaskWithArbitraryError(BaseCodecovTask):
    def __init__(self, error):
        self.error = error

    async def run_async(self, dbsession):
        raise self.error

    def retry(self):
        # Fake retry method
        raise Retry()


class SampleTaskWithArbitraryPostgresError(BaseCodecovTask):
    def __init__(self, error):
        self.error = error

    async def run_async(self, dbsession):
        raise DBAPIError("statement", "params", self.error)

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


class TestBaseCodecovTask(object):
    def test_hard_time_limit_task_with_request_data(self, mocker):
        mocker.patch.object(SampleTask, "request", timelimit=[200, 123])
        r = SampleTask()
        assert r.hard_time_limit_task == 200

    def test_hard_time_limit_task_from_default_app(self, mocker):
        mocker.patch.object(SampleTask, "request", timelimit=None)
        r = SampleTask()
        assert r.hard_time_limit_task == 480

    def test_sample_run(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        result = SampleTask().run()
        assert result == {"unusual": "return", "value": ["There"]}

    def test_sample_run_db_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryError(
                DBAPIError("statement", "params", "orig")
            ).run()

    def test_sample_run_integrity_error(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryError(
                IntegrityError("statement", "params", "orig")
            ).run()

    def test_sample_run_deadlock_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryPostgresError(
                psycopg2.errors.DeadlockDetected()
            ).run()

    def test_sample_run_operationalerror_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryPostgresError(psycopg2.OperationalError()).run()

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

    def test_wrap_up_dbsession_invalid_nothing_works(self, mocker):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        task = BaseCodecovTask()
        fake_session = mocker.MagicMock(
            commit=mocker.MagicMock(side_effect=[InvalidRequestError()])
        )
        task.wrap_up_dbsession(fake_session)
        assert fake_session.commit.call_count == 1
        assert fake_session.close.call_count == 0
        assert mocked_get_db_session.remove.call_count == 1


class TestBaseCodecovTaskHooks(object):
    def test_sample_task_success(self, celery_app, mocker):
        class SampleTask(BaseCodecovTask):
            name = "test.SampleTask"

            async def run_async(self, dbsession):
                return {"unusual": "return", "value": ["There"]}

        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        DTask = celery_app.register_task(SampleTask())
        task = celery_app.tasks[DTask.name]
        k = task.apply()
        res = k.get()
        assert res == {"unusual": "return", "value": ["There"]}
        mock_metrics.assert_called_with("worker.task.test.SampleTask.successes")

    def test_sample_task_failure(self, celery_app, mocker):
        class FailureSampleTask(BaseCodecovTask):
            name = "test.FailureSampleTask"

            async def run_async(self, *args, **kwargs):
                raise Exception("Whhhhyyyyyyy")

        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        DTask = celery_app.register_task(FailureSampleTask())
        task = celery_app.tasks[DTask.name]
        with pytest.raises(Exception) as exc:
            task.apply().get()
        assert exc.value.args == ("Whhhhyyyyyyy",)
        mock_metrics.assert_called_with("worker.task.test.FailureSampleTask.failures")

    def test_sample_task_retry(self, celery_app, mocker):
        # Unfortunately we cant really call the task with apply().get()
        # Something happens inside celery as of version 4.3 that makes them
        #   not call on_Retry at all.
        # best we can do is to call on_retry ourselves and ensure this makes the
        # metric be called
        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        task = RetrySampleTask()
        task.on_retry("exc", "task_id", "args", "kwargs", "einfo")
        mock_metrics.assert_called_with("worker.task.test.RetrySampleTask.retries")


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
        class SampleTask(BaseCodecovTask):
            name = "test.SampleTask"

        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        DTask = celery_app.register_task(SampleTask())
        request = self.xRequest(mocker, DTask.name, celery_app)
        request.on_timeout(True, 10)
        mock_metrics.assert_called_with("worker.task.test.SampleTask.timeout")

    def test_sample_task_hard_timeout(self, celery_app, mocker):
        class SampleTask(BaseCodecovTask):
            name = "test.SampleTask"

        mock_metrics = mocker.patch("tasks.base.metrics.incr")
        DTask = celery_app.register_task(SampleTask())
        request = self.xRequest(mocker, DTask.name, celery_app)
        request.on_timeout(False, 10)
        mock_metrics.assert_any_call("worker.task.test.SampleTask.hardtimeout")
        mock_metrics.assert_any_call("worker.task.test.SampleTask.timeout")


class TestBaseCodecovTaskApplyAsyncOverride(object):
    @pytest.fixture
    def fake_owners(self, dbsession):
        owner = OwnerFactory.create(plan=BillingPlan.pr_monthly.db_name)
        owner_enterprise_cloud = OwnerFactory.create(
            plan=BillingPlan.enterprise_cloud_yearly.db_name
        )
        dbsession.add(owner)
        dbsession.add(owner_enterprise_cloud)
        dbsession.flush()
        return (owner, owner_enterprise_cloud)

    @pytest.fixture
    def fake_repos(self, dbsession, fake_owners):
        (owner, owner_enterprise_cloud) = fake_owners
        repo = RepositoryFactory.create(owner=owner)
        repo_enterprise_cloud = RepositoryFactory.create(owner=owner_enterprise_cloud)
        dbsession.add(repo)
        dbsession.add(repo_enterprise_cloud)
        dbsession.flush()
        return (repo, repo_enterprise_cloud)

    def test_apply_async_override(self, mocker):

        mock_get_db_session = mocker.patch("tasks.base.get_db_session")
        mock_celery_task_router = mocker.patch("tasks.base._get_user_plan_from_task")
        mock_route_tasks = mocker.patch(
            "tasks.base.route_tasks_based_on_user_plan",
            return_value=dict(
                queue="some_queue",
                extra_config=dict(soft_timelimit=200, hard_timelimit=400),
            ),
        )

        task = BaseCodecovTask()
        task.name = "app.tasks.upload.FakeTask"
        mocked_apply_async = mocker.patch.object(base_celery_app.Task, "apply_async")

        kwargs = dict(n=10)
        task.apply_async(kwargs=kwargs)
        assert mock_get_db_session.call_count == 1
        assert mock_celery_task_router.call_count == 1
        assert mock_route_tasks.call_count == 1
        mocked_apply_async.assert_called_with(
            args=None,
            kwargs=kwargs,
            time_limit=400,
            soft_time_limit=200,
        )

    def test_apply_async_override_with_chain(self, mocker):

        mock_get_db_session = mocker.patch("tasks.base.get_db_session")
        mock_celery_task_router = mocker.patch("tasks.base._get_user_plan_from_task")
        mock_route_tasks = mocker.patch(
            "tasks.base.route_tasks_based_on_user_plan",
            return_value=dict(
                queue="some_queue",
                extra_config=dict(soft_timelimit=200, hard_timelimit=400),
            ),
        )

        task = BaseCodecovTask()
        task.name = "app.tasks.upload.FakeTask"
        mocked_apply_async = mocker.patch.object(base_celery_app.Task, "apply_async")

        chain(
            [task.signature(kwargs=dict(n=1)), task.signature(kwargs=dict(n=10))]
        ).apply_async()
        assert mock_get_db_session.call_count == 1
        assert mock_celery_task_router.call_count == 1
        assert mock_route_tasks.call_count == 1
        assert mocked_apply_async.call_count == 1
        _, kwargs = mocked_apply_async.call_args
        assert "soft_time_limit" in kwargs and kwargs.get("soft_time_limit") == 200
        assert "time_limit" in kwargs and kwargs.get("time_limit") == 400
        assert "kwargs" in kwargs and kwargs.get("kwargs") == {"n": 1}
        assert "chain" in kwargs and len(kwargs.get("chain")) == 1
        assert "task_id" in kwargs

    def test_real_example_no_override(
        self, mocker, dbsession, mock_configuration, fake_repos
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "tasks": {
                        "celery": {
                            "enterprise": {
                                "soft_timelimit": 500,
                                "hard_timelimit": 600,
                            },
                        },
                        "upload": {
                            "enterprise": {"soft_timelimit": 400, "hard_timelimit": 450}
                        },
                    }
                }
            }
        )
        mock_get_db_session = mocker.patch(
            "tasks.base.get_db_session", return_value=dbsession
        )
        task = BaseCodecovTask()
        mocker.patch.object(task, "run", return_value="success")
        task.name = sync_repos_task_name

        mocked_super_apply_async = mocker.patch.object(
            base_celery_app.Task, "apply_async"
        )
        repo, _ = fake_repos

        kwargs = dict(ownerid=repo.ownerid)
        task.apply_async(kwargs=kwargs)
        assert mock_get_db_session.call_count == 1
        mocked_super_apply_async.assert_called_with(
            args=None,
            kwargs=kwargs,
            soft_time_limit=None,
            time_limit=None,
        )

    def test_real_example_override_from_celery(
        self, mocker, dbsession, mock_configuration, fake_repos
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "tasks": {
                        "celery": {
                            "enterprise": {
                                "soft_timelimit": 500,
                                "hard_timelimit": 600,
                            },
                        },
                        "upload": {
                            "enterprise": {"soft_timelimit": 400, "hard_timelimit": 450}
                        },
                    }
                }
            }
        )
        mock_get_db_session = mocker.patch(
            "tasks.base.get_db_session", return_value=dbsession
        )
        task = BaseCodecovTask()
        mocker.patch.object(task, "run", return_value="success")
        task.name = sync_repos_task_name

        mocked_super_apply_async = mocker.patch.object(
            base_celery_app.Task, "apply_async"
        )
        _, repo_enterprise_cloud = fake_repos

        kwargs = dict(ownerid=repo_enterprise_cloud.ownerid)
        task.apply_async(kwargs=kwargs)
        assert mock_get_db_session.call_count == 1
        mocked_super_apply_async.assert_called_with(
            args=None,
            kwargs=kwargs,
            soft_time_limit=500,
            time_limit=600,
        )

    def test_real_example_override_from_upload(
        self, mocker, dbsession, mock_configuration, fake_repos
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "tasks": {
                        "celery": {
                            "enterprise": {
                                "soft_timelimit": 500,
                                "hard_timelimit": 600,
                            },
                        },
                        "upload": {
                            "enterprise": {"soft_timelimit": 400, "hard_timelimit": 450}
                        },
                    }
                }
            }
        )
        mock_get_db_session = mocker.patch(
            "tasks.base.get_db_session", return_value=dbsession
        )
        task = BaseCodecovTask()
        mocker.patch.object(task, "run", return_value="success")
        task.name = upload_task_name

        mocked_super_apply_async = mocker.patch.object(
            base_celery_app.Task, "apply_async"
        )
        _, repo_enterprise_cloud = fake_repos

        kwargs = dict(repoid=repo_enterprise_cloud.repoid)
        task.apply_async(kwargs=kwargs)
        assert mock_get_db_session.call_count == 1
        mocked_super_apply_async.assert_called_with(
            args=None,
            kwargs=kwargs,
            soft_time_limit=400,
            time_limit=450,
        )
