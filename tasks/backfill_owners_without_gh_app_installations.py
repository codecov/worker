import logging
from typing import List, Optional

from shared.config import get_config
from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import (
    backfill_owners_without_gh_app_installation_individual_name,
    backfill_owners_without_gh_app_installations_name,
)
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Owner,
)
from helpers.backfills import (
    add_repos_service_ids_from_provider,
    maybe_set_installation_to_all_repos,
)
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class BackfillOwnersWithoutGHAppInstallations(
    BaseCodecovTask, name=backfill_owners_without_gh_app_installations_name
):
    def backfill_owners_with_integration_without_gh_app(
        self,
        db_session: Session,
        owner_ids: List[int] = None,
        yield_amount: int = 1000,
    ):
        owners_with_integration_id_without_gh_app_query = (
            db_session.query(Owner)
            .outerjoin(
                GithubAppInstallation,
                Owner.ownerid == GithubAppInstallation.ownerid,
            )
            .filter(
                GithubAppInstallation.ownerid == None,  # noqa: E711
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

        owners: List[Owner] = owners_with_integration_id_without_gh_app_query.yield_per(
            yield_amount
        )

        for owner in owners:
            ownerid = owner.ownerid
            try:
                owner_service = get_owner_provider_service(owner=owner)

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
            except Exception:
                log.info(
                    "Backfill unsuccessful for this owner", extra=dict(ownerid=ownerid)
                )

    def run_impl(
        self,
        db_session: Session,
        owner_ids: Optional[List[int]] = None,
        yield_amount: int = 1000,
        *args,
        **kwargs,
    ):
        log.info(
            "Starting backfill for owners without gh app task",
        )

        # Backfill owners with legacy integration + adding new gh app
        owners_with_integration_id_without_gh_app_query = (
            db_session.query(Owner)
            .outerjoin(
                GithubAppInstallation,
                Owner.ownerid == GithubAppInstallation.ownerid,
            )
            .filter(
                GithubAppInstallation.ownerid is None,
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

        owners: List[Owner] = owners_with_integration_id_without_gh_app_query.yield_per(
            yield_amount
        )

        for owner in owners:
            self.app.tasks[
                backfill_owners_without_gh_app_installation_individual_name
            ].apply_async(kwargs=dict(ownerid=owner.ownerid))

        return {"successful": True, "reason": "backfill tasks queued"}


RegisterOwnersWithoutGHAppInstallations = celery_app.register_task(
    BackfillOwnersWithoutGHAppInstallations()
)
backfill_owners_without_gh_app_installations = celery_app.tasks[
    RegisterOwnersWithoutGHAppInstallations.name
]


class BackfillOwnersWithoutGHAppInstallationIndividual(
    BaseCodecovTask, name=backfill_owners_without_gh_app_installation_individual_name
):
    def run_impl(
        self,
        db_session: Session,
        ownerid: int,
        *args,
        **kwargs,
    ):
        owner = db_session.query(Owner).get(ownerid)

        log.info(
            "Attempt to create GH App",
            extra=dict(owner_id=ownerid, parent_id=self.request.parent_id),
        )

        try:
            owner_service = get_owner_provider_service(owner=owner)

            # Create new GH app installation and add all repos the gh app has access to
            log.info(
                "This owner has no Github App Installation",
                extra=dict(ownerid=ownerid, parent_id=self.request.parent_id),
            )
            gh_app_installation = GithubAppInstallation(
                owner=owner,
                installation_id=owner.integration_id,
                app_id=get_config("github", "integration", "id"),
                name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            )
            db_session.add(gh_app_installation)

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


RegisterOwnersWithoutGHAppInstallationIndividual = celery_app.register_task(
    BackfillOwnersWithoutGHAppInstallationIndividual()
)
backfill_owners_without_gh_app_installation_individual = celery_app.tasks[
    RegisterOwnersWithoutGHAppInstallationIndividual.name
]
