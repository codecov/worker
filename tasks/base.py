import asyncio
import logging

from celery.worker.request import Request
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import SQLAlchemyError, InvalidRequestError

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
        metrics.incr(f"{self.metrics_prefix}.timeout")
        return res


class BaseCodecovTask(celery_app.Task):
    Request = BaseCodecovRequest

    @property
    def metrics_prefix(self):
        return f"worker.task.{self.name}"

    def run(self, *args, **kwargs):
        with metrics.timer(f"{self.metrics_prefix}.full"):
            loop = asyncio.get_event_loop()
            db_session = get_db_session()
            try:
                with metrics.timer(f"{self.metrics_prefix}.run"):
                    return loop.run_until_complete(
                        self.run_async(db_session, *args, **kwargs)
                    )
            except SQLAlchemyError:
                log.exception(
                    "An error talking to the database occurred",
                    extra=dict(task_args=args, task_kwargs=kwargs),
                )
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
