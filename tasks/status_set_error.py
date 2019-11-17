import logging
import re

from app import celery_app
from celery_config import status_set_error_task_name
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StatusSetErrorTask(BaseCodecovTask):
    """
    """
    name = status_set_error_task_name

    async def run_async(self, db_session, repoid, commitid, *, message=None, **kwargs):
        log.info(
            'Set error',
            extra=dict(repoid=repoid, commitid=commitid, message=message)
        )

RegisteredStatusSetErrorTask = celery_app.register_task(StatusSetErrorTask())
status_set_error_task = celery_app.tasks[StatusSetErrorTask.name]
