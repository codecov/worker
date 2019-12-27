import logging
from datetime import datetime

from app import celery_app
from celery_config import delete_owner_task_name
from tasks.base import BaseCodecovTask
from database.models import Owner, Repository
from services.archive import ArchiveService

log = logging.getLogger(__name__)


class DeleteOwnerTask(BaseCodecovTask):
    """
    Delete an owner and their data:
    - Repo archive data for each of their owned repos
    - Owner entry from db
    - Cascading deletes of repos, pulls, and branches for the owner
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

        self.delete_repo_archives(db_session, ownerid)

        self.delete_owner_from_orgs(db_session, ownerid)

        # finally delete the actual owner entry and depending data from other tables]
        db_session.delete(owner)

    def delete_repo_archives(self, db_session, ownerid):
        """
        Delete all of the data stored in archives for owned repos
        """
        repos_for_owner = db_session.query(Repository).filter(
                Repository.ownerid == ownerid
        ).all()

        for repo in repos_for_owner:
            archive_service = ArchiveService(repo)
            archive_service.delete_repo_files()

    def delete_owner_from_orgs(self, db_session, ownerid):
        """
        Remove this owner wherever they exist in the organizations column of the owners table
        """
        owners_in_org = db_session.query(Owner).filter(
            Owner.organizations.any(ownerid)
        ).all()

        for owner in owners_in_org:
            owner.organizations.remove(ownerid)


RegisteredDeleteOwnerTask = celery_app.register_task(DeleteOwnerTask())
delete_owner_task = celery_app.tasks[DeleteOwnerTask.name]
