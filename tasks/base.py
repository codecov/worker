import logging
from datetime import datetime

import sentry_sdk
from celery._state import get_current_task
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
from celery.worker.request import Request
from django.db import transaction as django_transaction
from shared.celery_router import route_tasks_based_on_user_plan
from shared.metrics import Counter, Histogram
from shared.timeseries.helpers import is_timeseries_enabled
from shared.torngit import AdditionalData
from shared.torngit.base import TorngitBaseAdapter
from sqlalchemy.exc import (
    DataError,
    IntegrityError,
    InvalidRequestError,
    SQLAlchemyError,
)

from app import celery_app
from celery_task_router import _get_user_plan_from_task
from database.engine import get_db_session
from database.enums import CommitErrorTypes
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    Commit,
    Repository,
)
from helpers.checkpoint_logger import from_kwargs as load_checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import TestResultsFlow, UploadFlow
from helpers.clock import get_seconds_to_next_hour
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from helpers.log_context import LogContext, set_log_context
from helpers.save_commit_error import save_commit_error
from helpers.telemetry import TimeseriesTimer, log_simple_metric
from services.repository import get_repo_provider_service

log = logging.getLogger("worker")

REQUEST_TIMEOUT_COUNTER = Counter(
    "worker_task_counts_timeouts",
    "Number of times a task experienced any kind of timeout",
    ["task"],
)
REQUEST_HARD_TIMEOUT_COUNTER = Counter(
    "worker_task_counts_hard_timeouts",
    "Number of times a task experienced a hard timeout",
    ["task"],
)


class BaseCodecovRequest(Request):
    @property
    def metrics_prefix(self):
        return f"worker.task.{self.name}"

    def on_timeout(self, soft: bool, timeout: int):
        res = super().on_timeout(soft, timeout)
        if not soft:
            REQUEST_HARD_TIMEOUT_COUNTER.labels(task=self.name).inc()
        REQUEST_TIMEOUT_COUNTER.labels(task=self.name).inc()

        if UploadFlow.has_begun():
            UploadFlow.log(UploadFlow.CELERY_TIMEOUT)
        if TestResultsFlow.has_begun():
            TestResultsFlow.log(TestResultsFlow.CELERY_TIMEOUT)

        return res


# Task reliability metrics
TASK_RUN_COUNTER = Counter(
    "worker_task_counts_runs", "Number of times this task was run", ["task"]
)
TASK_RETRY_COUNTER = Counter(
    "worker_task_counts_retries", "Number of times this task was retried", ["task"]
)
TASK_SUCCESS_COUNTER = Counter(
    "worker_task_counts_successes",
    "Number of times this task completed without error",
    ["task"],
)
TASK_FAILURE_COUNTER = Counter(
    "worker_task_counts_failures",
    "Number of times this task failed with an exception",
    ["task"],
)

# Task runtime metrics
TASK_FULL_RUNTIME = Histogram(
    "worker_task_timers_full_runtime_seconds",
    "Total runtime in seconds of this task including db commits and error handling",
    ["task"],
    buckets=[0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 180, 300, 600, 900],
)
TASK_CORE_RUNTIME = Histogram(
    "worker_task_timers_core_runtime_seconds",
    "Runtime in seconds of this task's main logic, not including db commits or error handling",
    ["task"],
    buckets=[0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 180, 300, 600, 900],
)
TASK_TIME_IN_QUEUE = Histogram(
    "worker_tasks_timers_time_in_queue_seconds",
    "Time in {TODO} spent waiting in the queue before being run",
    ["task", "queue"],
    buckets=[
        0.01,
        0.05,
        0.1,
        0.25,
        0.5,
        0.75,
        1,
        1.5,
        2,
        3,
        5,
        7,
        10,
        15,
        20,
        30,
        45,
        60,
        90,
        120,
        180,
    ],
)


class BaseCodecovTask(celery_app.Task):
    Request = BaseCodecovRequest

    def __init_subclass__(cls, name=None):
        cls.name = name

        cls.metrics_prefix = f"worker.task.{name}"

        # Task reliability metrics
        cls.task_run_counter = TASK_RUN_COUNTER.labels(task=name)
        cls.task_retry_counter = TASK_RETRY_COUNTER.labels(task=name)
        cls.task_success_counter = TASK_SUCCESS_COUNTER.labels(task=name)
        cls.task_failure_counter = TASK_FAILURE_COUNTER.labels(task=name)

        # Task runtime metrics
        cls.task_full_runtime = TASK_FULL_RUNTIME.labels(task=name)
        cls.task_core_runtime = TASK_CORE_RUNTIME.labels(task=name)

    @property
    def hard_time_limit_task(self):
        if self.request.timelimit is not None and self.request.timelimit[0] is not None:
            return self.request.timelimit[0]
        if self.time_limit is not None:
            return self.time_limit
        return self.app.conf.task_time_limit or 0

    @sentry_sdk.trace
    def apply_async(self, args=None, kwargs=None, **options):
        db_session = get_db_session()
        user_plan = _get_user_plan_from_task(db_session, self.name, kwargs)
        route_with_extra_config = route_tasks_based_on_user_plan(self.name, user_plan)
        extra_config = route_with_extra_config.get("extra_config", {})
        celery_compatible_config = {
            "time_limit": extra_config.get("hard_timelimit", None),
            "soft_time_limit": extra_config.get("soft_timelimit", None),
            "user_plan": user_plan,
        }
        options = {**options, **celery_compatible_config}

        opt_headers = options.pop("headers", {})
        opt_headers = opt_headers if opt_headers is not None else {}

        # Pass current time in task headers so we can emit a metric of
        # how long the task was in the queue for
        current_time = datetime.now()
        headers = {
            **opt_headers,
            "created_timestamp": current_time.isoformat(),
        }
        return super().apply_async(args=args, kwargs=kwargs, headers=headers, **options)

    def _commit_django(self):
        try:
            django_transaction.commit()
        except Exception as e:
            log.warning(
                "Django transaction failed to commit.",
                exc_info=True,
                extra=dict(e=e),
            )

        if is_timeseries_enabled():
            try:
                django_transaction.commit("timeseries")
            except Exception as e:
                log.warning(
                    "Django transaction failed to commit in the timeseries database.",
                    exc_info=True,
                    extra=dict(e=e),
                )

    def _rollback_django(self):
        try:
            django_transaction.rollback()
        except Exception as e:
            log.warning(
                "Django transaction failed to roll back.",
                exc_info=True,
                extra=dict(e=e),
            )

        if is_timeseries_enabled():
            try:
                django_transaction.rollback("timeseries")
            except Exception as e:
                log.warning(
                    "Django transaction failed to roll back in the timeseries database.",
                    exc_info=True,
                    extra=dict(e=e),
                )

    # Called when attempting to retry the task on db error
    def _retry(self):
        try:
            self.retry()
        except MaxRetriesExceededError:
            if UploadFlow.has_begun():
                UploadFlow.log(UploadFlow.UNCAUGHT_RETRY_EXCEPTION)
            if TestResultsFlow.has_begun():
                TestResultsFlow.log(TestResultsFlow.UNCAUGHT_RETRY_EXCEPTION)

    def _analyse_error(self, exception: SQLAlchemyError, *args, **kwargs):
        try:
            import psycopg2

            if hasattr(exception, "orig") and isinstance(
                exception.orig, psycopg2.errors.DeadlockDetected
            ):
                log.exception(
                    "Deadlock while talking to database",
                    extra=dict(task_args=args, task_kwargs=kwargs),
                    exc_info=True,
                )
                return
            elif hasattr(exception, "orig") and isinstance(
                exception.orig, psycopg2.OperationalError
            ):
                log.warning(
                    "Database seems to be unavailable",
                    extra=dict(task_args=args, task_kwargs=kwargs),
                    exc_info=True,
                )
                return
        except ImportError:
            pass
        log.exception(
            "An error talking to the database occurred",
            extra=dict(task_args=args, task_kwargs=kwargs),
            exc_info=True,
        )

    def _emit_queue_metrics(self):
        created_timestamp = self.request.get("created_timestamp", None)
        if created_timestamp:
            enqueued_time = datetime.fromisoformat(created_timestamp)
            now = datetime.now()
            delta = now - enqueued_time

            queue_name = self.request.get("delivery_info", {}).get("routing_key", None)
            time_in_queue_timer = TASK_TIME_IN_QUEUE.labels(
                task=self.name, queue=queue_name
            )  # TODO is None a valid label value
            time_in_queue_timer.observe(delta.total_seconds())

    def run(self, *args, **kwargs):
        with self.task_full_runtime.time():  # Timer isn't tested
            db_session = get_db_session()

            log_context = LogContext(
                repo_id=kwargs.get("repoid") or kwargs.get("repo_id"),
                owner_id=kwargs.get("ownerid"),
                commit_sha=kwargs.get("commitid") or kwargs.get("commit_id"),
            )

            task = get_current_task()
            if task and task.request:
                log_context.task_name = task.name
                log_context.task_id = task.request.id

            log_context.populate_from_sqlalchemy(db_session)
            set_log_context(log_context)
            load_checkpoints_from_kwargs([UploadFlow, TestResultsFlow], kwargs)

            self.task_run_counter.inc()
            self._emit_queue_metrics()

            try:
                with TimeseriesTimer(f"{self.metrics_prefix}.core_runtime", sync=True):
                    with self.task_core_runtime.time():  # Timer isn't tested
                        return self.run_impl(db_session, *args, **kwargs)
            except (DataError, IntegrityError):
                log.exception(
                    "Errors related to the constraints of database happened",
                    extra=dict(task_args=args, task_kwargs=kwargs),
                )
                db_session.rollback()
                self._rollback_django()
                self._retry()
            except SQLAlchemyError as ex:
                self._analyse_error(ex, args, kwargs)
                db_session.rollback()
                self._rollback_django()
                self._retry()
            except MaxRetriesExceededError as ex:
                if UploadFlow.has_begun():
                    UploadFlow.log(UploadFlow.UNCAUGHT_RETRY_EXCEPTION)
                if TestResultsFlow.has_begun():
                    TestResultsFlow.log(TestResultsFlow.UNCAUGHT_RETRY_EXCEPTION)
            finally:
                self.wrap_up_dbsession(db_session)
                self._commit_django()

    def wrap_up_dbsession(self, db_session):
        """
        Wraps up dbsession, commita what is relevant and closes the session

        This function deals with the very corner case of when a `SoftTimeLimitExceeded`
            is raised during the execution of `db_session.commit()`. When it happens,
            the dbsession gets into a bad state, which disallows further operations in it.

        And because we reuse dbsessions, this would mean future tasks happening inside the
            same process would also lose access to db.

        So we need to do two ugly exception-catching:
            1) For if `SoftTimeLimitExceeded` was raised  while commiting
            2) For if the exception left `db_session` in an unusable state
        """
        try:
            db_session.commit()
            db_session.close()
        except SoftTimeLimitExceeded:
            log.warning(
                "We had an issue where a timeout happened directly during the DB commit",
                exc_info=True,
            )
            try:
                db_session.commit()
                db_session.close()
            except InvalidRequestError:
                log.warning(
                    "DB session cannot be operated on any longer. Closing it and removing it",
                    exc_info=True,
                )
                get_db_session.remove()
        except InvalidRequestError:
            log.warning(
                "DB session cannot be operated on any longer. Closing it and removing it",
                exc_info=True,
            )
            get_db_session.remove()

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        res = super().on_retry(exc, task_id, args, kwargs, einfo)
        self.task_retry_counter.inc()
        log_simple_metric(f"{self.metrics_prefix}.retry", 1.0)
        return res

    def on_success(self, retval, task_id, args, kwargs):
        res = super().on_success(retval, task_id, args, kwargs)
        self.task_success_counter.inc()
        log_simple_metric(f"{self.metrics_prefix}.success", 1.0)
        return res

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """
        Includes SoftTimeLimitExceeded, for example
        """
        res = super().on_failure(exc, task_id, args, kwargs, einfo)
        self.task_failure_counter.inc()
        log_simple_metric(f"{self.metrics_prefix}.failure", 1.0)

        if UploadFlow.has_begun():
            UploadFlow.log(UploadFlow.CELERY_FAILURE)
        if TestResultsFlow.has_begun():
            TestResultsFlow.log(TestResultsFlow.CELERY_FAILURE)

        return res

    def get_repo_provider_service(
        self,
        repository: Repository,
        installation_name_to_use: str = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        additional_data: AdditionalData = None,
        commit: Commit = None,
    ) -> TorngitBaseAdapter:
        try:
            return get_repo_provider_service(
                repository, installation_name_to_use, additional_data
            )
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit,
                error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
                error_params=dict(repoid=commit.repoid),
            )
            log.warning(
                "Unable to reach git provider because repo doesn't have a valid bot"
            )
        except NoConfiguredAppsAvailable as exp:
            if exp.rate_limited_count > 0:
                # There's at least 1 app that we can use to communicate with GitHub,
                # but this app happens to be rate limited now. We try again later.
                # Min wait time of 1 minute
                retry_delay_seconds = max(60, get_seconds_to_next_hour())
                log.warning(
                    "Unable to get repo provider service due to rate limits. Retrying again later.",
                    extra=dict(
                        apps_available=exp.apps_count,
                        apps_rate_limited=exp.rate_limited_count,
                        apps_suspended=exp.suspended_count,
                        countdown_seconds=retry_delay_seconds,
                    ),
                )
            else:
                log.warning(
                    "Unable to get repo provider service. Apps appear to be suspended.",
                    extra=dict(
                        apps_available=exp.apps_count,
                        apps_rate_limited=exp.rate_limited_count,
                        apps_suspended=exp.suspended_count,
                        countdown_seconds=retry_delay_seconds,
                    ),
                )
        except Exception as e:
            log.exception("Uncaught exception when trying to get repository service")
