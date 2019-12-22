import logging
from datetime import datetime

from app import celery_app
from celery_config import delete_owner_task_name
from tasks.base import BaseCodecovTask
from database.models import Owner

log = logging.getLogger(__name__)


class DeleteOwnerTask(BaseCodecovTask):
    """
    """
    name = delete_owner_task_name

    async def run_async(self, db_session, ownerid):
        log.info(
            'Delete owner',
            extra=dict(ownerid=ownerid)
        )
        owner = db_session.query(Owner).filter(
            Owner.ownerid == ownerid
        ).first()

        assert owner, 'Owner not found'


RegisteredDeleteOwnerTask = celery_app.register_task(DeleteOwnerTask())
delete_owner_task = celery_app.tasks[DeleteOwnerTask.name]
