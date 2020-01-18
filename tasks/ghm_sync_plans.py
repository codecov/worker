import logging

from app import celery_app
from celery_config import ghm_sync_plans_task_name
from database.models import Owner, Repository
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

class SyncPlansTask(BaseCodecovTask):
    """
    Sync GitHub marketplace plans
    """
    name = ghm_sync_plans_task_name

    async def run_async(self, db_session, sender=None, account=None, action=None):
        log.info(
            'GitHub marketplace sync plans',
            extra=dict(sender=sender, account=account, action=action)
        )

RegisteredGHMSyncPlansTask = celery_app.register_task(SyncPlansTask())
ghm_sync_plans_task = celery_app.tasks[SyncPlansTask.name]
