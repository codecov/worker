import logging
from typing import List, Optional

from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import backfill_existing_gh_app_installations_name
from database.models.core import GithubAppInstallation, Owner
from helpers.backfills import (
    add_repos_service_ids_from_provider,
    maybe_set_installation_to_all_repos,
)
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

YIELD_AMOUNT = 100


class BackfillExistingGHAppInstallationsTask(
    BaseCodecovTask, name=backfill_existing_gh_app_installations_name
):
    def backfill_existing_gh_apps(
        self, db_session: Session, owner_ids: List[int] = None, missed_owner_ids=[]
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

        gh_app_installations: List[GithubAppInstallation] = (
            gh_app_installations_query.yield_per(YIELD_AMOUNT)
        )

        for gh_app_installation in gh_app_installations:
            # Check if gh app has 'all' repositories selected
            owner = gh_app_installation.owner
            ownerid = gh_app_installation.owner.ownerid

            try:
                owner_service = get_owner_provider_service(
                    owner=owner, using_integration=True
                )
                is_selection_all = maybe_set_installation_to_all_repos(
                    db_session=db_session,
                    owner_service=owner_service,
                    gh_app_installation=gh_app_installation,
                )

                if not is_selection_all:
                    # Find and add all repos the gh app has access to
                    add_repos_service_ids_from_provider(
                        db_session=db_session,
                        ownerid=ownerid,
                        owner_service=owner_service,
                        gh_app_installation=gh_app_installation,
                    )
                    log.info("Successful backfill", extra=dict(ownerid=ownerid))
            except:
                log.info(
                    "Backfill unsuccessful for this owner", extra=dict(ownerid=ownerid)
                )
                missed_owner_ids.append(ownerid)
                continue
        del gh_app_installations

    def run_impl(
        self,
        db_session: Session,
        owner_ids: Optional[List[int]] = None,
        *args,
        **kwargs,
    ):
        log.info(
            "Starting Existing GH App backfill task",
        )

        missed_owner_ids = []

        # Backfill gh apps we already have
        self.backfill_existing_gh_apps(
            db_session=db_session,
            owner_ids=owner_ids,
            missed_owner_ids=missed_owner_ids,
        )

        log.info(
            "Backfill for existing gh apps completed",
        )

        log.info(
            "Potential owner ids that didn't backfill",
            extra=dict(missed_owner_ids=missed_owner_ids),
        )

        return {"successful": True, "reason": "backfill task finished"}


RegisteredBackfillExistingGHAppInstallationsTask = celery_app.register_task(
    BackfillExistingGHAppInstallationsTask()
)
backfill_existing_gh_app_installations_task = celery_app.tasks[
    RegisteredBackfillExistingGHAppInstallationsTask.name
]
