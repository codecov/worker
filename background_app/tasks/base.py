from app import celery_app
import asyncio


class BaseCodecovTask(celery_app.Task):

    def run(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.run_async(*args, **kwargs))
