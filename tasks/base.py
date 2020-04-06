import asyncio
import logging

from celery.worker.request import Request
from sqlalchemy.exc import SQLAlchemyError

from app import celery_app
from database.engine import get_db_session
from helpers.metrics import metrics


log = logging.getLogger("worker")


class BaseCodecovRequest(Request):

    @property
    def metrics_prefix(self):
        return f"new-worker.task.{self.name}"

    def on_timeout(self, soft: bool, timeout: int):
        res = super().on_timeout(soft, timeout)
        metrics.incr(f"{self.metrics_prefix}.timeout")
        return res


class BaseCodecovTask(celery_app.Task):
    Request = BaseCodecovRequest

    @property
    def metrics_prefix(self):
        return f"new-worker.task.{self.name}"

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
                if self.write_to_db():
                    db_session.commit()
                db_session.close()

    def write_to_db(self):
        return True

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
