import logging
import os
from enum import Enum
from sqlalchemy import func

from database.models import Owner


log = logging.getLogger(__name__)


class Decoration(Enum):
    standard = "standard"
    upgrade = "upgrade"


def is_whitelisted(ownerid) -> bool:
    pr_billing_whitelisted_owners = [
        int(ownerid.strip())
        for ownerid in os.getenv("PR_AUTHOR_BILLING_WHITELISTED_OWNERS", "").split()
    ]

    return ownerid in pr_billing_whitelisted_owners


def get_decoration_type(db_session, enriched_pull):
    """
    Determine which type of decoration we should do
    """
    if enriched_pull:
        db_pull = enriched_pull.database_pull
        provider_pull = enriched_pull.provider_pull

        if not provider_pull:
            return (Decoration.standard, "Can't determine PR author - no pull info from provider")

        if db_pull.repository.private is False:
            # public repo or repo we arent certain is private should be standard
            return (Decoration.standard, "Public repo")

        org = db_pull.repository.owner

        if not org.plan in ["users-inappm-pr", "users-inappy-pr"]:
            return (Decoration.standard, "Org not on PR plan")

        if not is_whitelisted(org.ownerid):
            return (Decoration.standard, "Org not in whitelist")

        pr_author = (
            db_session.query(Owner)
            .filter(
                Owner.service == org.service,
                Owner.service_id == provider_pull["author"]["id"],
            )
            .first()
        )

        if not pr_author:
            log.info(
                "PR author not found in database",
                extra=dict(
                    author_service=org.service,
                    author_service_id=provider_pull["author"]["id"],
                    author_username=provider_pull["author"]["username"],
                ),
            )
            return (Decoration.upgrade, "PR author not found in database")

        if not pr_author.ownerid in org.plan_activated_users and org.plan_auto_activate:
            log.info(
                "Attempting PR author auto activation",
                extra=dict(
                    org_ownerid=org.ownerid,
                    author_ownerid=pr_author.ownerid,
                    pullid=db_pull.pullid,
                ),
            )

            # TODO: we need to decide the best way for this logic to be shared across
            # worker and codecov-api - ideally moving logic from database to application layer
            (activation_success,) = db_session.query(
                func.public.try_to_auto_activate(org.ownerid, pr_author.ownerid)
            ).first()

            if not activation_success:
                log.info(
                    "PR author auto activation was not successful",
                    extra=dict(
                        org_ownerid=org.ownerid,
                        author_ownerid=pr_author.ownerid,
                        pullid=db_pull.pullid,
                    ),
                )
                return (Decoration.upgrade, "PR author auto activation failed")

            # TODO: activation was successful so we should run the future NewUserActivatedTask
            return (Decoration.standard, "PR author auto activation success")
        else:
            return (Decoration.upgrade, "User must be manually activated")

    return (Decoration.standard, "No pull")
