import logging

import shared.torngit as torngit
from sqlalchemy import String
from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import backfill_gh_app_installations
from database.models.core import GithubAppInstallation, Owner, Repository
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class BackfillGHAppInstallationsTask(
    BaseCodecovTask, name=backfill_gh_app_installations
):
    # Looping and adding all repositories in the installation app
    async def add_repos_service_ids_from_provider(
        self,
        db_session: Session,
        ownerid: int,
        owner_service: torngit.base.TorngitBaseAdapter,
        gh_app_installation: GithubAppInstallation,
    ):
        repos = await owner_service.list_repos_using_installation()
        if repos:
            # Fetching all repos service ids we have for that owner in the DB
            repo_service_ids_in_db = [
                repo.service_id
                for repo in db_session.query(Repository.service_id)
                .filter_by(ownerid=ownerid)
                .all()
            ]

            # Add service ids from provider that we have DB records for to a list
            new_repo_service_ids = set()
            current_repo_service_ids = set(
                gh_app_installation.repository_service_ids or []
            )
            for repo in repos:
                repo_data = repo["repo"]
                service_id = repo_data["service_id"]
                if service_id and service_id in repo_service_ids_in_db:
                    new_repo_service_ids.add(service_id)
            log.info(
                "Added the following repo service ids to this gh app installation",
                extra=dict(
                    ownerid=ownerid,
                    installation_id=gh_app_installation.installation_id,
                    new_repo_service_ids=list(new_repo_service_ids),
                ),
            )
            gh_app_installation.repository_service_ids = list(
                current_repo_service_ids.union(new_repo_service_ids)
            )
            db_session.commit()

    async def run_async(
        self, db_session: Session, ownerid: String, service: String, *args, **kwargs
    ):
        # Check if service isn't github
        if service != "github":
            log.info(
                "No installation work needed for non-github orgs",
                extra=dict(ownerid=ownerid),
            )
            return {"successful": True, "reason": "no installation needed"}

        # Check if the owner exists
        owner: Owner = (
            db_session.query(Owner).filter_by(ownerid=ownerid, service=service).first()
        )

        if not owner:
            log.exception(
                "There is no owner DB record",
                extra=dict(ownerid=ownerid, service=service),
            )
            return {"successful": False, "reason": "no owner found"}

        # Check if owner any sort of integration
        if not owner.integration_id:
            log.info("No installation work needed", extra=dict(ownerid=ownerid))
            return {"successful": True, "reason": "no installation needed"}

        # Check if owner has a gh app installation entry
        gh_app_installation: GithubAppInstallation = (
            db_session.query(GithubAppInstallation).filter_by(ownerid=ownerid).first()
        )
        owner_service = get_owner_provider_service(owner=owner, using_integration=True)

        if gh_app_installation:
            # Check if gh app has 'all' repositories selected
            installation_id = gh_app_installation.installation_id

            remote_gh_app_installation = await owner_service.get_gh_app_installation(
                installation_id=installation_id
            )
            repository_selection = remote_gh_app_installation.get(
                "repository_selection", ""
            )
            if repository_selection == "all":
                gh_app_installation.repository_service_ids = None
                db_session.commit()
                return {"successful": True, "reason": "selection is set to all"}

            # Otherwise, find and add all repos the gh app has access to
            await self.add_repos_service_ids_from_provider(
                db_session=db_session,
                ownerid=ownerid,
                owner_service=owner_service,
                gh_app_installation=gh_app_installation,
            )
            return {"successful": True, "reason": "successful backfill"}
        else:
            # Create new GH app installation and add all repos the gh app has access to
            log.info(
                "This owner has no Github App Installation",
                extra=dict(ownerid=ownerid),
            )
            new_gh_app_installation = GithubAppInstallation(
                owner=owner, installation_id=owner.integration_id
            )
            db_session.add(new_gh_app_installation)
            db_session.commit()

            # Find and add all repos the gh app has access to
            await self.add_repos_service_ids_from_provider(
                db_session=db_session,
                ownerid=ownerid,
                owner_service=owner_service,
                gh_app_installation=new_gh_app_installation,
            )
            return {"successful": True, "reason": "successful backfill"}


RegisteredBackfillGHAppInstallationsTask = celery_app.register_task(
    BackfillGHAppInstallationsTask()
)
backfill_gh_app_installations_task = celery_app.tasks[
    RegisteredBackfillGHAppInstallationsTask.name
]
