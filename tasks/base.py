import asyncio
import logging
from datetime import datetime

from celery.exceptions import SoftTimeLimitExceeded
from celery.worker.request import Request
from prometheus_client import REGISTRY
from shared.celery_router import route_tasks_based_on_user_plan
from shared.metrics import Counter, Histogram
from sqlalchemy.exc import (
    DataError,
    IntegrityError,
    InvalidRequestError,
    SQLAlchemyError,
)

from app import celery_app
from celery_task_router import _get_user_plan_from_task
from database.engine import get_db_session
from helpers.metrics import metrics

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
            metrics.incr(f"{self.metrics_prefix}.hardtimeout")
        REQUEST_TIMEOUT_COUNTER.labels(task=self.name).inc()
        metrics.incr(f"{self.metrics_prefix}.timeout")
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

    def apply_async(self, args=None, kwargs=None, **options):
        db_session = get_db_session()
        user_plan = _get_user_plan_from_task(db_session, self.name, kwargs)
        route_with_extra_config = route_tasks_based_on_user_plan(self.name, user_plan)
        extra_config = route_with_extra_config.get("extra_config", {})
        celery_compatible_config = {
            "time_limit": extra_config.get("hard_timelimit", None),
            "soft_time_limit": extra_config.get("soft_timelimit", None),
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

    def _analyse_error(self, exception: SQLAlchemyError, *args, **kwargs):
        try:
            import psycopg2

            if isinstance(exception.orig, psycopg2.errors.DeadlockDetected):
                log.exception(
                    "Deadlock while talking to database",
                    extra=dict(task_args=args, task_kwargs=kwargs),
                    exc_info=True,
                )
                return
            elif isinstance(exception.orig, psycopg2.OperationalError):
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
            metrics.timing(f"{self.metrics_prefix}.time_in_queue", delta)

            queue_name = self.request.get("delivery_info", {}).get("routing_key", None)
            time_in_queue_timer = TASK_TIME_IN_QUEUE.labels(
                task=self.name, queue=queue_name
            )  # TODO is None a valid label value
            time_in_queue_timer.observe(delta.total_seconds())

            if queue_name:
                metrics.timing(f"worker.queues.{queue_name}.time_in_queue", delta)
                metrics.timing(
                    f"{self.metrics_prefix}.{queue_name}.time_in_queue", delta
                )

    def run(self, *args, **kwargs):
        self.task_run_counter.inc()
        self._emit_queue_metrics()
        with self.task_full_runtime.time():  # Timer isn't tested
            with metrics.timer(f"{self.metrics_prefix}.full"):
                db_session = get_db_session()
                try:
                    with self.task_core_runtime.time():  # Timer isn't tested
                        with metrics.timer(f"{self.metrics_prefix}.run"):
                            return asyncio.run(
                                self.run_async(db_session, *args, **kwargs)
                            )
                except (DataError, IntegrityError):
                    log.exception(
                        "Errors related to the constraints of database happened",
                        extra=dict(task_args=args, task_kwargs=kwargs),
                    )
                    db_session.rollback()
                    self.retry()
                except SQLAlchemyError as ex:
                    self._analyse_error(ex, args, kwargs)
                    db_session.rollback()
                    self.retry()
                finally:
                    self.wrap_up_dbsession(db_session)

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

    def on_retry(self, *args, **kwargs):
        res = super().on_retry(*args, **kwargs)
        self.task_retry_counter.inc()
        metrics.incr(f"{self.metrics_prefix}.retries")
        return res

    def on_success(self, *args, **kwargs):
        res = super().on_success(*args, **kwargs)
        self.task_success_counter.inc()
        metrics.incr(f"{self.metrics_prefix}.successes")
        return res

    def on_failure(self, *args, **kwargs):
        """
        Includes SoftTimeoutLimitException, for example
        """
        res = super().on_failure(*args, **kwargs)
        self.task_failure_counter.inc()
        metrics.incr(f"{self.metrics_prefix}.failures")
        return res
