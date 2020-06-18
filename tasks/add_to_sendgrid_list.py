import logging
from app import celery_app
from database.models import Owner
from tasks.base import BaseCodecovTask
from services.archive import ArchiveService
from services.sendgrid_service import Sendgrid

log = logging.getLogger(__name__)


class AddToSendgridListTask(BaseCodecovTask):
    async def run_async(
        self, db_session, ownerid, list_type=None, email_type=None, *args, **kwargs
    ):
        actual_type = (
            list_type or email_type
        )  # stopgap as we switch from email_type to list_type
        if actual_type is None:
            log.error(
                "Did not receive a Sendgrid list or email type",
                extra=dict(ownerid=ownerid),
            )
            return None

        log.info(
            "Add to Sendgrid List", extra=dict(ownerid=ownerid, list_type=actual_type)
        )
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
        return email_helper.add_to_list(owner.email)


RegisteredAddToSendgridListTask = celery_app.register_task(AddToSendgridListTask())
add_to_sendgrid_list_task = celery_app.tasks[RegisteredAddToSendgridListTask.name]
