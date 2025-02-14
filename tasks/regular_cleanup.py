import logging

from celery.exceptions import SoftTimeLimitExceeded

from app import celery_app
from celery_config import regular_cleanup_cron_task_name
from services.cleanup.regular import run_regular_cleanup
from services.cleanup.utils import CleanupSummary
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class RegularCleanupTask(BaseCodecovTask, name=regular_cleanup_cron_task_name):
    acks_late = True  # retry the task when the worker dies for whatever reason
    max_retries = None  # aka, no limit on retries

    def run_impl(self, _db_session, *args, **kwargs) -> CleanupSummary:
        try:
            return run_regular_cleanup()
        except SoftTimeLimitExceeded:
            raise self.retry()


RegisteredRegularCleanupTask = celery_app.register_task(RegularCleanupTask())
regular_cleanup_task = celery_app.tasks[RegisteredRegularCleanupTask.name]
