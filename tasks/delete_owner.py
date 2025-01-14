import logging

from shared.celery_config import delete_owner_task_name
from shared.django_apps.codecov_auth.models import Owner

from app import celery_app
from services.cleanup.cleanup import run_cleanup
from services.cleanup.owner import clear_owner
from services.cleanup.utils import CleanupSummary
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class DeleteOwnerTask(BaseCodecovTask, name=delete_owner_task_name):
    """
    Delete an owner and their data:
    - Repo archive data for each of their owned repos
    - Owner entry from db
    - Cascading deletes of repos, pulls, and branches for the owner
    """

    def run_impl(self, _db_session, ownerid: int) -> CleanupSummary:
        log.info("Delete owner", extra={"ownerid": ownerid})

        clear_owner(ownerid)
        owner_query = Owner.objects.filter(ownerid=ownerid)

        summary = run_cleanup(owner_query)
        log.info("Deletion finished", extra={"ownerid": ownerid, "summary": summary})
        return summary


RegisteredDeleteOwnerTask = celery_app.register_task(DeleteOwnerTask())
delete_owner_task = celery_app.tasks[DeleteOwnerTask.name]
