import logging
from typing import List, Optional

import shared.torngit as torngit
from asgiref.sync import async_to_sync
from shared.config import get_config
from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import backfill_gh_app_installations_without_gh_app_name
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Owner,
    Repository,
)
from helpers.backfills import (
    add_repos_service_ids_from_provider,
    maybe_set_installation_to_all_repos,
)
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

yield_amount = 100


class BackfillGHAppInstallationsWithoutGHAppTask(
    BaseCodecovTask, name=backfill_gh_app_installations_without_gh_app_name
):
    def backfill_owners_with_integration_without_gh_app(
        self, db_session: Session, owner_ids: List[int] = None, missed_owner_ids=[]
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

        owners: List[
            Owner
        ] = owners_with_integration_id_without_gh_app_query.all().yield_per(
            yield_amount
        )

        for owner in owners:
            ownerid = owner.ownerid
            try:
                owner_service = get_owner_provider_service(
                    owner=owner, using_integration=True
                )

                # Create new GH app installation and add all repos the gh app has access to
                log.info(
                    "This owner has no Github App Installation",
                    extra=dict(ownerid=ownerid),
                )
                gh_app_installation = GithubAppInstallation(
                    owner=owner,
                    installation_id=owner.integration_id,
                    app_id=get_config("github", "integration", "id"),
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                )
                db_session.add(gh_app_installation)
                db_session.commit()

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
                del owner_service
            except:
                log.info(
                    "Backfill unsuccessful for this owner", extra=dict(ownerid=ownerid)
                )
                missed_owner_ids.append(ownerid)
                continue
        del owners

    def run_impl(
        self,
        db_session: Session,
        owner_ids: Optional[List[int]] = None,
        *args,
        **kwargs
    ):
        log.info(
            "Starting backfill for owners without gh app task",
        )

        missed_owner_ids = []

        # Backfill owners with legacy integration + adding new gh app
        self.backfill_owners_with_integration_without_gh_app(
            db_session=db_session,
            owner_ids=owner_ids,
            missed_owner_ids=missed_owner_ids,
        )

        log.info(
            "Backfill for owners without apps finished",
        )

        log.info(
            "Potential owner ids that didn't backfill",
            extra=dict(missed_owner_ids=missed_owner_ids),
        )

        return {"successful": True, "reason": "backfill task finished"}


RegisteredBackfillGHAppInstallationsWithoutGHAppTask = celery_app.register_task(
    BackfillGHAppInstallationsWithoutGHAppTask()
)
backfill_gh_app_installations_task = celery_app.tasks[
    RegisteredBackfillGHAppInstallationsWithoutGHAppTask.name
]
