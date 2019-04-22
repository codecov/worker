import asyncio
import logging

from app import celery_app
from database.engine import get_db_session

logger = logging.getLogger('worker')


class BaseCodecovTask(celery_app.Task):

    def run(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        db_session = get_db_session()
        result = loop.run_until_complete(self.run_async(db_session, *args, **kwargs))
        if self.write_to_db():
            db_session.commit()
        return result
