from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import psycopg2
import pytest
from celery import chain
from celery.contrib.testing.mocks import TaskMessage
from celery.exceptions import Retry, SoftTimeLimitExceeded
from mock import ANY, call
from prometheus_client import REGISTRY
from shared.celery_config import sync_repos_task_name, upload_task_name
from shared.plan.constants import PlanName
from shared.utils.test_utils import mock_config_helper
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InvalidRequestError,
    StatementError,
)

from database.enums import CommitErrorTypes
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.tests.factories.core import OwnerFactory, RepositoryFactory
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from tasks.base import BaseCodecovRequest, BaseCodecovTask
from tasks.base import celery_app as base_celery_app
from tests.helpers import mock_all_plans_and_tiers

here = Path(__file__)


class MockDateTime(datetime):
    """
    `@pytest.mark.freeze_time()` is convenient but will freeze time for
    everything, including timeseries metrics for which a timestamp is
    a primary key.

    This class can be used to mock time more narrowly.
    """

    @classmethod
    def now(cls):
        return datetime.fromisoformat("2023-06-13T10:01:01.000123")


class SampleTask(BaseCodecovTask, name="test.SampleTask"):
    def run_impl(self, dbsession):
        return {"unusual": "return", "value": ["There"]}


class SampleTaskWithArbitraryError(
    BaseCodecovTask, name="test.SampleTaskWithArbitraryError"
):
    def __init__(self, error):
        self.error = error

    def run_impl(self, dbsession):
        raise self.error

    def retry(self, countdown=None):
        # Fake retry method
        raise Retry()


class SampleTaskWithArbitraryPostgresError(
    BaseCodecovTask, name="test.SampleTaskWithArbitraryPostgresError"
):
    def __init__(self, error):
        self.error = error

    def run_impl(self, dbsession):
        raise DBAPIError("statement", "params", self.error)

    def retry(self, countdown=None):
        # Fake retry method
        raise Retry()


class SampleTaskWithSoftTimeout(BaseCodecovTask, name="test.SampleTaskWithSoftTimeout"):
    def run_impl(self, dbsession):
        raise SoftTimeLimitExceeded()


class FailureSampleTask(BaseCodecovTask, name="test.FailureSampleTask"):
    def run_impl(self, *args, **kwargs):
        raise Exception("Whhhhyyyyyyy")


class RetrySampleTask(BaseCodecovTask, name="test.RetrySampleTask"):
    def run(self, *args, **kwargs):
        self.retry()


@pytest.mark.django_db(databases={"default", "timeseries"})
class TestBaseCodecovTask(object):
    def test_hard_time_limit_task_with_request_data(self, mocker):
        mocker.patch.object(SampleTask, "request", timelimit=[200, 123])
        r = SampleTask()
        assert r.hard_time_limit_task == 200

    def test_hard_time_limit_task_from_default_app(self, mocker):
        mocker.patch.object(SampleTask, "request", timelimit=None)
        r = SampleTask()
        assert r.hard_time_limit_task == 480

    @patch("tasks.base.datetime", MockDateTime)
    @patch("helpers.telemetry.log_simple_metric")
    def test_sample_run(self, mock_simple_metric, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mock_task_request = mocker.patch("tasks.base.BaseCodecovTask.request")
        fake_request_values = dict(
            created_timestamp="2023-06-13 10:00:00.000000",
            delivery_info={"routing_key": "my-queue"},
        )
        mock_task_request.get.side_effect = (
            lambda key, default: fake_request_values.get(key, default)
        )
        mocked_get_db_session.return_value = dbsession
        task_instance = SampleTask()
        result = task_instance.run()
        assert result == {"unusual": "return", "value": ["There"]}
        assert (
            REGISTRY.get_sample_value(
                "worker_tasks_timers_time_in_queue_seconds_sum",
                labels={"task": SampleTask.name, "queue": "my-queue"},
            )
            == 61.000123
        )
        mock_simple_metric.assert_has_calls(
            [call("worker.task.test.SampleTask.core_runtime", ANY)]
        )

    @patch("tasks.base.BaseCodecovTask._emit_queue_metrics")
    def test_sample_run_db_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryError(
                DBAPIError("statement", "params", "orig")
            ).run()

    @patch("tasks.base.BaseCodecovTask._emit_queue_metrics")
    def test_sample_run_integrity_error(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryError(
                IntegrityError("statement", "params", "orig")
            ).run()

    @patch("tasks.base.BaseCodecovTask._emit_queue_metrics")
    def test_sample_run_deadlock_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryPostgresError(
                psycopg2.errors.DeadlockDetected()
            ).run()

    @patch("tasks.base.BaseCodecovTask._emit_queue_metrics")
    def test_sample_run_operationalerror_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithArbitraryPostgresError(psycopg2.OperationalError()).run()

    @patch("tasks.base.BaseCodecovTask._emit_queue_metrics")
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

    def test_commit_django_with_timeseries(self, mocker):
        mock_config_helper(mocker, configs={"setup.timeseries.enabled": True})
        mock_commit = mocker.patch("tasks.base.django_transaction.commit")
        task = BaseCodecovTask()
        task._commit_django()
        assert mock_commit.call_args_list == [call(), call("timeseries")]

    def test_commit_django_without_timeseries(self, mocker):
        mock_config_helper(mocker, configs={"setup.timeseries.enabled": False})
        mock_commit = mocker.patch("tasks.base.django_transaction.commit")
        task = BaseCodecovTask()
        task._commit_django()
        assert mock_commit.call_args_list == [call()]

    def test_rollback_django_with_timeseries(self, mocker):
        mock_config_helper(mocker, configs={"setup.timeseries.enabled": True})
        mock_rollback = mocker.patch("tasks.base.django_transaction.rollback")
        task = BaseCodecovTask()
        task._rollback_django()
        assert mock_rollback.call_args_list == [call(), call("timeseries")]

    def test_rollback_django_without_timeseries(self, mocker):
        mock_config_helper(mocker, configs={"setup.timeseries.enabled": False})
        mock_rollback = mocker.patch("tasks.base.django_transaction.rollback")
        task = BaseCodecovTask()
        task._rollback_django()
        assert mock_rollback.call_args_list == [call()]

    def test_run_success_commits_both_orms(self, mocker, dbsession):
        mock_django_commit = mocker.patch("tasks.base.BaseCodecovTask._commit_django")
        mock_wrap_up = mocker.patch("tasks.base.BaseCodecovTask.wrap_up_dbsession")
        mock_django_rollback = mocker.patch(
            "tasks.base.BaseCodecovTask._rollback_django"
        )
        mock_dbsession_rollback = mocker.patch.object(dbsession, "rollback")
        mock_get_db_session = mocker.patch(
            "tasks.base.get_db_session", return_value=dbsession
        )

        task = SampleTask()
        task.run()

        assert mock_django_commit.call_args_list == [call()]
        assert mock_wrap_up.call_args_list == [call(dbsession)]

        assert mock_django_rollback.call_count == 0
        assert mock_dbsession_rollback.call_count == 0

    def test_run_db_errors_rollback(self, mocker, dbsession, celery_app):
        mock_django_commit = mocker.patch("tasks.base.BaseCodecovTask._commit_django")
        mock_django_rollback = mocker.patch(
            "tasks.base.BaseCodecovTask._rollback_django"
        )
        mock_dbsession_rollback = mocker.patch.object(dbsession, "rollback")
        mock_wrap_up = mocker.patch("tasks.base.BaseCodecovTask.wrap_up_dbsession")
        mock_get_db_session = mocker.patch(
            "tasks.base.get_db_session", return_value=dbsession
        )

        # IntegrityError and DataError are subclasses of SQLAlchemyError that
        # have their own `except` clause.
        task = SampleTaskWithArbitraryError(IntegrityError("", {}, None))
        registered_task = celery_app.register_task(task)
        task = celery_app.tasks[registered_task.name]
        task.apply()

        assert mock_django_rollback.call_args_list == [call()]
        assert mock_dbsession_rollback.call_args_list == [call()]

        assert mock_django_commit.call_args_list == [call()]
        assert mock_wrap_up.call_args_list == [call(dbsession)]

    def test_run_sqlalchemy_error_rollback(self, mocker, dbsession, celery_app):
        mock_django_commit = mocker.patch("tasks.base.BaseCodecovTask._commit_django")
        mock_django_rollback = mocker.patch(
            "tasks.base.BaseCodecovTask._rollback_django"
        )
        mock_dbsession_rollback = mocker.patch.object(dbsession, "rollback")
        mock_wrap_up = mocker.patch("tasks.base.BaseCodecovTask.wrap_up_dbsession")
        mock_get_db_session = mocker.patch(
            "tasks.base.get_db_session", return_value=dbsession
        )

        # StatementError is a subclass of SQLAlchemyError just like
        # IntegrityError and DataError, but this test case is different because
        # it is caught by a different except clause.
        task = SampleTaskWithArbitraryError(StatementError("", "", None, None))
        registered_task = celery_app.register_task(task)
        task = celery_app.tasks[registered_task.name]
        task.apply()

        assert mock_django_rollback.call_args_list == [call()]
        assert mock_dbsession_rollback.call_args_list == [call()]

        assert mock_django_commit.call_args_list == [call()]
        assert mock_wrap_up.call_args_list == [call(dbsession)]

    def test_get_repo_provider_service_working(self, mocker):
        mock_repo_provider = mocker.MagicMock()
        mock_get_repo_provider_service = mocker.patch(
            "tasks.base.get_repo_provider_service", return_value=mock_repo_provider
        )

        task = BaseCodecovTask()
        mock_repo = mocker.MagicMock()
        assert task.get_repo_provider_service(mock_repo) == mock_repo_provider
        mock_get_repo_provider_service.assert_called_with(
            mock_repo, GITHUB_APP_INSTALLATION_DEFAULT_NAME, None
        )

    def test_get_repo_provider_service_rate_limited(self, mocker):
        mocker.patch(
            "tasks.base.get_repo_provider_service",
            side_effect=NoConfiguredAppsAvailable(
                apps_count=2,
                rate_limited_count=2,
                suspended_count=0,
            ),
        )
        mocker.patch("tasks.base.get_seconds_to_next_hour", return_value=120)

        task = BaseCodecovTask()
        mock_retry = mocker.patch.object(task, "retry")
        mock_repo = mocker.MagicMock()
        assert task.get_repo_provider_service(mock_repo) is None
        task.retry.assert_called_with(countdown=120)

    def test_get_repo_provider_service_suspended(self, mocker):
        mocker.patch(
            "tasks.base.get_repo_provider_service",
            side_effect=NoConfiguredAppsAvailable(
                apps_count=2,
                rate_limited_count=0,
                suspended_count=2,
            ),
        )
        mocker.patch("tasks.base.get_seconds_to_next_hour", return_value=120)

        task = BaseCodecovTask()
        mock_repo = mocker.MagicMock()
        assert task.get_repo_provider_service(mock_repo) is None

    def test_get_repo_provider_service_no_valid_bot(self, mocker):
        mocker.patch(
            "tasks.base.get_repo_provider_service",
            side_effect=RepositoryWithoutValidBotError(),
        )
        mock_save_commit_error = mocker.patch("tasks.base.save_commit_error")

        task = BaseCodecovTask()
        mock_repo = mocker.MagicMock()
        mock_repo.repoid = 5
        mock_commit = mocker.MagicMock()
        assert task.get_repo_provider_service(mock_repo, commit=mock_commit) is None
        mock_save_commit_error.assert_called_with(
            mock_commit,
            error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
            error_params=dict(repoid=5),
        )


@pytest.mark.django_db(databases={"default", "timeseries"})
class TestBaseCodecovTaskHooks(object):
    def test_sample_task_success(self, celery_app):
        class SampleTask(BaseCodecovTask, name="test.SampleTask"):
            def run_impl(self, dbsession):
                return {"unusual": "return", "value": ["There"]}

        DTask = celery_app.register_task(SampleTask())
        task = celery_app.tasks[DTask.name]

        prom_run_counter_before = REGISTRY.get_sample_value(
            "worker_task_counts_runs_total", labels={"task": DTask.name}
        )
        prom_success_counter_before = REGISTRY.get_sample_value(
            "worker_task_counts_successes_total", labels={"task": DTask.name}
        )
        k = task.apply()
        prom_run_counter_after = REGISTRY.get_sample_value(
            "worker_task_counts_runs_total", labels={"task": DTask.name}
        )
        prom_success_counter_after = REGISTRY.get_sample_value(
            "worker_task_counts_successes_total", labels={"task": DTask.name}
        )

        res = k.get()
        assert res == {"unusual": "return", "value": ["There"]}
        assert prom_run_counter_after - prom_run_counter_before == 1
        assert prom_success_counter_after - prom_success_counter_before == 1

    def test_sample_task_failure(self, celery_app):
        class FailureSampleTask(BaseCodecovTask, name="test.FailureSampleTask"):
            def run_impl(self, *args, **kwargs):
                raise Exception("Whhhhyyyyyyy")

        DTask = celery_app.register_task(FailureSampleTask())
        task = celery_app.tasks[DTask.name]
        with pytest.raises(Exception) as exc:
            prom_run_counter_before = REGISTRY.get_sample_value(
                "worker_task_counts_runs_total", labels={"task": DTask.name}
            )
            prom_failure_counter_before = REGISTRY.get_sample_value(
                "worker_task_counts_failures_total", labels={"task": DTask.name}
            )
            task.apply().get()
            prom_run_counter_after = REGISTRY.get_sample_value(
                "worker_task_counts_runs_total", labels={"task": DTask.name}
            )
            prom_failure_counter_after = REGISTRY.get_sample_value(
                "worker_task_counts_failures_total", labels={"task": DTask.name}
            )
            assert prom_run_counter_after - prom_run_counter_before == 1
            assert prom_failure_counter_after - prom_failure_counter_before == 1
        assert exc.value.args == ("Whhhhyyyyyyy",)

    def test_sample_task_retry(self):
        # Unfortunately we cant really call the task with apply().get()
        # Something happens inside celery as of version 4.3 that makes them
        #   not call on_Retry at all.
        # best we can do is to call on_retry ourselves and ensure this makes the
        # metric be called
        task = RetrySampleTask()
        prom_retry_counter_before = REGISTRY.get_sample_value(
            "worker_task_counts_retries_total", labels={"task": task.name}
        )
        task.on_retry("exc", "task_id", ("args",), {"kwargs": "foo"}, "einfo")
        prom_retry_counter_after = REGISTRY.get_sample_value(
            "worker_task_counts_retries_total", labels={"task": task.name}
        )
        assert prom_retry_counter_after - prom_retry_counter_before == 1


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
        class SampleTask(BaseCodecovTask, name="test.SampleTask"):
            pass

        DTask = celery_app.register_task(SampleTask())
        request = self.xRequest(mocker, DTask.name, celery_app)
        prom_timeout_counter_before = (
            REGISTRY.get_sample_value(
                "worker_task_counts_timeouts_total", labels={"task": DTask.name}
            )
            or 0
        )
        request.on_timeout(True, 10)
        prom_timeout_counter_after = REGISTRY.get_sample_value(
            "worker_task_counts_timeouts_total", labels={"task": DTask.name}
        )
        assert prom_timeout_counter_after - prom_timeout_counter_before == 1

    def test_sample_task_hard_timeout(self, celery_app, mocker):
        class SampleTask(BaseCodecovTask, name="test.SampleTask"):
            pass

        DTask = celery_app.register_task(SampleTask())
        request = self.xRequest(mocker, DTask.name, celery_app)
        prom_timeout_counter_before = (
            REGISTRY.get_sample_value(
                "worker_task_counts_timeouts_total", labels={"task": DTask.name}
            )
            or 0
        )
        prom_hard_timeout_counter_before = (
            REGISTRY.get_sample_value(
                "worker_task_counts_hard_timeouts_total", labels={"task": DTask.name}
            )
            or 0
        )
        request.on_timeout(False, 10)
        prom_timeout_counter_after = REGISTRY.get_sample_value(
            "worker_task_counts_timeouts_total", labels={"task": DTask.name}
        )
        prom_hard_timeout_counter_after = REGISTRY.get_sample_value(
            "worker_task_counts_hard_timeouts_total", labels={"task": DTask.name}
        )
        assert prom_timeout_counter_after - prom_timeout_counter_before == 1
        assert prom_hard_timeout_counter_after - prom_hard_timeout_counter_before == 1


class TestBaseCodecovTaskApplyAsyncOverride(object):
    @pytest.fixture
    def fake_owners(self, dbsession):
        owner = OwnerFactory.create(plan=PlanName.CODECOV_PRO_MONTHLY.value)
        owner_enterprise_cloud = OwnerFactory.create(
            plan=PlanName.ENTERPRISE_CLOUD_YEARLY.value
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

    @pytest.mark.freeze_time("2023-06-13T10:01:01.000123")
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
            headers=dict(created_timestamp="2023-06-13T10:01:01.000123"),
            time_limit=400,
            soft_time_limit=200,
            user_plan=mock_celery_task_router(),
        )

    @pytest.mark.freeze_time("2023-06-13T10:01:01.000123")
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
        assert "headers" in kwargs
        assert kwargs.get("headers") == dict(
            created_timestamp="2023-06-13T10:01:01.000123"
        )

    @pytest.mark.freeze_time("2023-06-13T10:01:01.000123")
    @pytest.mark.django_db(databases={"default"})
    def test_real_example_no_override(
        self, mocker, dbsession, mock_configuration, fake_repos
    ):
        mock_all_plans_and_tiers()
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
            headers=dict(created_timestamp="2023-06-13T10:01:01.000123"),
            time_limit=None,
            user_plan="users-pr-inappm",
        )

    @pytest.mark.freeze_time("2023-06-13T10:01:01.000123")
    @pytest.mark.django_db(databases={"default"})
    def test_real_example_override_from_celery(
        self, mocker, dbsession, mock_configuration, fake_repos
    ):
        mock_all_plans_and_tiers()
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
            headers=dict(created_timestamp="2023-06-13T10:01:01.000123"),
            time_limit=600,
            user_plan="users-enterprisey",
        )

    @pytest.mark.freeze_time("2023-06-13T10:01:01.000123")
    @pytest.mark.django_db(databases={"default"})
    def test_real_example_override_from_upload(
        self, mocker, dbsession, mock_configuration, fake_repos
    ):
        mock_all_plans_and_tiers()
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
            headers=dict(created_timestamp="2023-06-13T10:01:01.000123"),
            time_limit=450,
            user_plan="users-enterprisey",
        )
