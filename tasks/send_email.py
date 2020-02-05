import logging 
from app import celery_app
from database.models import Owner
from tasks.base import BaseCodecovTask
from services.archive import ArchiveService
from services.sendgrid_service import Sendgrid

log = logging.getLogger(__name__)

class SendEmailTask(BaseCodecovTask):
    async def run_async(self, db_session, ownerid, email_type, *args, **kwargs):
        log.info(
            'Send email', 
            extra=dict(ownerid=ownerid, email_type=email_type)
        )
        # get owner object from database
        owners = db_session.query(Owner).filter_by(ownerid=ownerid)
        owner = owners.first()
        if not owner:
            log.error(
                'Unable to find owner',
                extra=dict(ownerid=ownerid, email_type=email_type)
            )
            return None
        email_helper = Sendgrid(email_type)
        return email_helper.send_email(owner)

RegisteredSendEmailTask = celery_app.register_task(SendEmailTask())
send_email = celery_app.tasks[RegisteredSendEmailTask.name]
