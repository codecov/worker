import asyncio
from json import dumps
import logging

from app import celery_app
from database.engine import get_db_session

logger = logging.getLogger('worker')


class BaseCodecovTask(celery_app.Task):

    def run(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        db_session = get_db_session()
        result = loop.run_until_complete(self.run_async(db_session, *args, **kwargs))
        db_session.commit()
        return result

    def log(self, lvl, message, public=True, **kwargs):
        kwargs['task'] = self.__class__.__name__.lower()

        if '?' in (kwargs.get('endpoint') or ''):
            kwargs['endpoint'] = kwargs['endpoint'][:kwargs['endpoint'].find('?')]

        message = '{} {}'.format(
            message,
            dumps(kwargs, sort_keys=True)
        )

        getattr(logger, lvl)(message)
