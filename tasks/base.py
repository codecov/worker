import asyncio
import logging

from app import celery_app
from database.engine import get_db_session
from sqlalchemy.exc import SQLAlchemyError
from helpers.metrics import metrics

log = logging.getLogger('worker')


class BaseCodecovTask(celery_app.Task):

    def run(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        db_session = get_db_session()
        try:
            with metrics.timer(f'new-worker.task.{self.name}.run'):
                return loop.run_until_complete(self.run_async(db_session, *args, **kwargs))
        except SQLAlchemyError:
            log.exception(
                "An error talking to the database occurred",
                extra=dict(task_args=args, task_kwargs=kwargs)
            )
            db_session.rollback()
            self.retry()
        finally:
            if self.write_to_db():
                db_session.commit()
            db_session.close()

    def write_to_db(self):
        return True
