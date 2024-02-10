import logging

import shared.torngit as torngit
from sqlalchemy import String
from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import backfill_gh_app_installations
from database.models.core import GithubAppInstallation, Owner
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
            new_repo_service_ids_set = set()
            current_repo_service_ids_set = set(
                gh_app_installation.repository_service_ids
            )
            for repo in repos:
                service_id = repo["repo"]["service_id"]
                if service_id:
                    new_repo_service_ids_set.add(service_id)
            log.info(
                "Added the following repo service ids to this gh app installation",
                extra=dict(
                    ownerid=ownerid,
                    installation_id=gh_app_installation.installation_id,
                    new_repo_service_ids=list(new_repo_service_ids_set),
                ),
            )
            gh_app_installation.repository_service_ids = list(
                current_repo_service_ids_set.union(new_repo_service_ids_set)
            )
            db_session.flush()

    async def run_async(
        self, db_session: Session, ownerid: String, service: String, *args, **kwargs
    ):
        owner: Owner = db_session.query(Owner).filter_by(
            ownerid=ownerid, service=service
        )
        if not owner:
            log.exception(
                "There is no owner DB record",
                extra=dict(ownerid=ownerid, service=service),
            )
            return {"successful": False, "reason": "no owner found"}

        gh_app_installation: GithubAppInstallation = (
            db_session.query(GithubAppInstallation).filter_by(ownerid=ownerid).first()
        )

        # Check if owner any sort of integration
        if owner.integration_id or gh_app_installation:
            if gh_app_installation:
                # Check if gh app has all repositories selected
                owner_service = get_owner_provider_service(owner=owner)
                installation_id = gh_app_installation.installation_id

                remote_gh_app_installation = (
                    await owner_service.get_gh_app_installation(
                        installation_id=installation_id
                    )
                )
                repository_selection = remote_gh_app_installation.get(
                    "repository_selection", ""
                )
                if repository_selection == "all":
                    gh_app_installation.repository_service_ids = None
                    db_session.flush()
                    return {"successful": True}

                await self.add_repos_service_ids_from_provider(
                    db_session=db_session,
                    ownerid=ownerid,
                    owner_service=owner_service,
                    gh_app_installation=gh_app_installation,
                )
                return {"successful": True}
            else:
                log.exception(
                    "This owner has no Github App Installation",
                    extra=dict(ownerid=ownerid),
                )
                # TODO: MISSING THIS STEP Create new records for GH app
                # call the list of repos
                await self.add_repos_service_ids_from_provider(
                    db_session=db_session,
                    ownerid=ownerid,
                    owner_service=owner_service,
                    gh_app_installation=gh_app_installation,
                )
                return {"successful": True}
        else:
            log.info("No integration work needed", extra=dict(ownerid=ownerid))
            return {"successful": True}


RegisteredBackfillGHAppInstallationsTask = celery_app.register_task(
    BackfillGHAppInstallationsTask()
)
backfill_gh_app_installations_task = celery_app.tasks[
    RegisteredBackfillGHAppInstallationsTask.name
]
