import logging
from typing import List, Optional

import shared.torngit as torngit
from asgiref.sync import async_to_sync
from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import backfill_gh_app_installations_name
from database.models.core import GithubAppInstallation, Owner, Repository
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class BackfillGHAppInstallationsTask(
    BaseCodecovTask, name=backfill_gh_app_installations_name
):
    # Looping and adding all repositories in the installation app
    def add_repos_service_ids_from_provider(
        self,
        db_session: Session,
        ownerid: int,
        owner_service: torngit.base.TorngitBaseAdapter,
        gh_app_installation: GithubAppInstallation,
    ):
        repos = async_to_sync(owner_service.list_repos_using_installation)()

        if repos:
            # Fetching all repos service ids we have for that owner in the DB
            repo_service_ids_in_db = [
                repo.service_id
                for repo in db_session.query(Repository.service_id)
                .filter_by(ownerid=ownerid)
                .all()
            ]

            # Add service ids from provider that we have DB records for to a list
            new_repo_service_ids = []
            for repo in repos:
                repo_data = repo["repo"]
                service_id = repo_data["service_id"]
                if service_id and service_id in repo_service_ids_in_db:
                    new_repo_service_ids.append(service_id)
            log.info(
                "Added the following repo service ids to this gh app installation",
                extra=dict(
                    ownerid=ownerid,
                    installation_id=gh_app_installation.installation_id,
                    new_repo_service_ids=new_repo_service_ids,
                ),
            )
            gh_app_installation.repository_service_ids = new_repo_service_ids
            db_session.commit()

    def backfill_existing_gh_apps(
        self, db_session: Session, owner_ids: List[int] = None
    ):
        # Get owners that have installations, and installations queries
        owners_query = (
            db_session.query(Owner)
            .join(GithubAppInstallation, Owner.ownerid == GithubAppInstallation.ownerid)
            .filter(
                Owner.service == "github",
            )
        )
        gh_app_installations_query = db_session.query(GithubAppInstallation)

        # Filter if owner_ids were provided
        if owner_ids:
            owners_query = owners_query.filter(Owner.ownerid.in_(owner_ids))
            gh_app_installations_query = gh_app_installations_query.filter(
                GithubAppInstallation.ownerid.in_(owner_ids)
            )

        owners: List[Owner] = owners_query.all()
        gh_app_installations: List[
            GithubAppInstallation
        ] = gh_app_installations_query.all()

        # I need to make reference of these in the gh installation app, Ill take suggestions here
        owners_dict = {owner.ownerid: owner for owner in owners}

        for gh_app_installation in gh_app_installations:
            # Check if gh app has 'all' repositories selected
            installation_id = gh_app_installation.installation_id

            owner = owners_dict[gh_app_installation.ownerid]
            ownerid = owner.ownerid

            owner_service = get_owner_provider_service(
                owner=owner, using_integration=True
            )

            remote_gh_app_installation = async_to_sync(
                owner_service.get_gh_app_installation
            )(installation_id=installation_id)
            repository_selection = remote_gh_app_installation.get(
                "repository_selection", ""
            )
            if repository_selection == "all":
                gh_app_installation.repository_service_ids = None
                db_session.commit()
                log.info(
                    "Selection is set to all, no installation is needed",
                    extra=dict(ownerid=ownerid),
                )
            else:
                # Find and add all repos the gh app has access to
                self.add_repos_service_ids_from_provider(
                    db_session=db_session,
                    ownerid=ownerid,
                    owner_service=owner_service,
                    gh_app_installation=gh_app_installation,
                )
                log.info("Successful backfill", extra=dict(ownerid=ownerid))

    def backfill_owners_with_integration_without_gh_app(
        self, db_session: Session, owner_ids: List[int] = None
    ):
        owners_with_integration_id_without_gh_app_query = (
            db_session.query(Owner)
            .outerjoin(
                GithubAppInstallation,
                Owner.ownerid == GithubAppInstallation.ownerid,
            )
            .filter(
                GithubAppInstallation.ownerid == None,
                Owner.integration_id.isnot(None),
                Owner.service == "github",
            )
        )

        if owner_ids:
            owners_with_integration_id_without_gh_app_query = (
                owners_with_integration_id_without_gh_app_query.filter(
                    Owner.ownerid.in_(owner_ids)
                )
            )

        owners: List[Owner] = owners_with_integration_id_without_gh_app_query.all()

        for owner in owners:
            ownerid = owner.ownerid
            owner_service = get_owner_provider_service(
                owner=owner, using_integration=True
            )

            # Create new GH app installation and add all repos the gh app has access to
            log.info(
                "This owner has no Github App Installation",
                extra=dict(ownerid=ownerid),
            )
            gh_app_installation = GithubAppInstallation(
                owner=owner, installation_id=owner.integration_id
            )
            db_session.add(gh_app_installation)
            db_session.commit()

            # Find and add all repos the gh app has access to
            self.add_repos_service_ids_from_provider(
                db_session=db_session,
                ownerid=ownerid,
                owner_service=owner_service,
                gh_app_installation=gh_app_installation,
            )
            log.info("Successful backfill", extra=dict(ownerid=ownerid))

    def run_impl(
        self,
        db_session: Session,
        owner_ids: Optional[List[int]] = None,
        *args,
        **kwargs
    ):
        # Backfill gh apps we already have
        self.backfill_existing_gh_apps(db_session=db_session, owner_ids=owner_ids)

        # Backfill owners with legacy integration + adding new gh app
        self.backfill_owners_with_integration_without_gh_app(
            db_session=db_session, owner_ids=owner_ids
        )

        log.info(
            "Complete backfill finished",
        )
        return {"successful": True, "reason": "backfill task finished"}


RegisteredBackfillGHAppInstallationsTask = celery_app.register_task(
    BackfillGHAppInstallationsTask()
)
backfill_gh_app_installations_task = celery_app.tasks[
    RegisteredBackfillGHAppInstallationsTask.name
]
