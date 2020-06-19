import logging
from app import celery_app
from database.models import Owner
from tasks.base import BaseCodecovTask
from services.archive import ArchiveService
from services.sendgrid_service import Sendgrid

log = logging.getLogger(__name__)


class SendEmailTask(BaseCodecovTask):
    async def run_async(self, db_session, ownerid, list_type=None, email_type=None, *args, **kwargs):
        actual_type = list_type or email_type
        if actual_type is None:
            log.error(
                "Did not receive a Sendgrid list or email type",
                extra=dict(ownerid=ownerid),
            )
            return None

        log.info("Send email", extra=dict(ownerid=ownerid, list_type=actual_type))
        # get owner object from database
        owners = db_session.query(Owner).filter_by(ownerid=ownerid)
        owner = owners.first()
        if not owner:
            log.error(
                "Unable to find owner",
                extra=dict(ownerid=ownerid, list_type=actual_type),
            )
            return None
        email_helper = Sendgrid(actual_type)
        return email_helper.send_email(owner)


RegisteredSendEmailTask = celery_app.register_task(SendEmailTask())
send_email = celery_app.tasks[RegisteredSendEmailTask.name]
