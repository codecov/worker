import asyncio
import logging

from celery.exceptions import SoftTimeLimitExceeded
from celery.worker.request import Request
from sqlalchemy.exc import (
    DataError,
    IntegrityError,
    InvalidRequestError,
    SQLAlchemyError,
)

from app import celery_app
from database.engine import get_db_session
from helpers.metrics import metrics

log = logging.getLogger("worker")


class BaseCodecovRequest(Request):
    @property
    def metrics_prefix(self):
        return f"worker.task.{self.name}"

    def on_timeout(self, soft: bool, timeout: int):
        res = super().on_timeout(soft, timeout)
        if not soft:
            metrics.incr(f"{self.metrics_prefix}.hardtimeout")
        metrics.incr(f"{self.metrics_prefix}.timeout")
        return res


class BaseCodecovTask(celery_app.Task):
    Request = BaseCodecovRequest

    @property
    def metrics_prefix(self):
        return f"worker.task.{self.name}"

    @property
    def hard_time_limit_task(self):
        if self.request.timelimit is not None and self.request.timelimit[0] is not None:
            return self.request.timelimit[0]
        if self.time_limit is not None:
            return self.time_limit
        return self.app.conf.task_time_limit or 0

    def _analyse_error(self, exception: SQLAlchemyError, *args, **kwargs):
        try:
            import psycopg2

            if isinstance(exception.orig, psycopg2.errors.DeadlockDetected):
                log.exception(
                    "Deadlock while talking to database",
                    extra=dict(task_args=args, task_kwargs=kwargs),
                )
                return
            elif isinstance(exception.orig, psycopg2.OperationalError):
                log.warning(
                    "Database seems to be unavailable",
                    extra=dict(task_args=args, task_kwargs=kwargs),
                )
                return
        except ImportError:
            pass
        log.exception(
            "An error talking to the database occurred",
            extra=dict(task_args=args, task_kwargs=kwargs),
        )

    def run(self, *args, **kwargs):
        with metrics.timer(f"{self.metrics_prefix}.full"):
            db_session = get_db_session()
            try:
                with metrics.timer(f"{self.metrics_prefix}.run"):
                    return asyncio.run(self.run_async(db_session, *args, **kwargs))
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
        metrics.incr(f"{self.metrics_prefix}.retries")
        return res

    def on_success(self, *args, **kwargs):
        res = super().on_success(*args, **kwargs)
        metrics.incr(f"{self.metrics_prefix}.successes")
        return res

    def on_failure(self, *args, **kwargs):
        """
        Includes SoftTimeoutLimitException, for example
        """
        res = super().on_failure(*args, **kwargs)
        metrics.incr(f"{self.metrics_prefix}.failures")
        return res
