import logging
from typing import List, Optional

from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import (
    backfill_existing_gh_app_installations_name,
    backfill_existing_individual_gh_app_installation_name,
)
from database.models.core import GithubAppInstallation, Owner
from helpers.backfills import (
    add_repos_service_ids_from_provider,
    maybe_set_installation_to_all_repos,
)
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class BackfillExistingGHAppInstallationsTask(
    BaseCodecovTask, name=backfill_existing_gh_app_installations_name
):
    def run_impl(
        self,
        db_session: Session,
        owner_ids: Optional[List[int]] = None,
        yield_amount: int = 1000,
        *args,
        **kwargs,
    ):
        log.info(
            "Starting Existing GH App backfill task",
        )

        # Backfill gh apps we already have
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
            gh_app_installations_query.yield_per(yield_amount)
        )

        for gh_app_installation in gh_app_installations:
            self.app.tasks[
                backfill_existing_individual_gh_app_installation_name
            ].apply_async(kwargs=dict(gh_app_installation_id=gh_app_installation.id))

        return {"successful": True, "reason": "backfill tasks queued"}


RegisteredBackfillExistingGHAppInstallationsTask = celery_app.register_task(
    BackfillExistingGHAppInstallationsTask()
)
backfill_existing_gh_app_installations_task = celery_app.tasks[
    RegisteredBackfillExistingGHAppInstallationsTask.name
]


class BackfillExistingIndividualGHAppInstallationTask(
    BaseCodecovTask, name=backfill_existing_individual_gh_app_installation_name
):
    def run_impl(
        self,
        db_session: Session,
        gh_app_installation_id: int,
        *args,
        **kwargs,
    ):
        gh_app_installation = db_session.query(GithubAppInstallation).get(
            gh_app_installation_id
        )

        # Check if gh app has 'all' repositories selected
        owner = gh_app_installation.owner
        ownerid = gh_app_installation.owner.ownerid

        log.info(
            "Attempt to backfill gh_app_installation",
            extra=dict(owner_id=ownerid, parent_id=self.request.parent_id),
        )

        try:
            owner_service = get_owner_provider_service(owner=owner)
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
            log.info(
                "Successful backfill",
                extra=dict(ownerid=ownerid, parent_id=self.request.parent_id),
            )
            return {"successful": True, "reason": "backfill task finished"}
        except Exception:
            log.info(
                "Backfill unsuccessful for this owner",
                extra=dict(ownerid=ownerid, parent_id=self.request.parent_id),
            )
            return {"successful": False, "reason": "backfill unsuccessful"}


RegisteredBackfillExistingIndividualGHAppInstallationTask = celery_app.register_task(
    BackfillExistingIndividualGHAppInstallationTask()
)
backfill_existing_individual_gh_app_installation_task = celery_app.tasks[
    RegisteredBackfillExistingIndividualGHAppInstallationTask.name
]
