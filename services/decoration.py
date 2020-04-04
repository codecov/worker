import logging
import os
from enum import Enum
from sqlalchemy import func

from database.models import Owner


log = logging.getLogger(__name__)


class Decoration(Enum):
    standard = "standard"
    upgrade = "upgrade"


def get_decoration_type(enriched_pull, commit):
    """ 
    Determine which type of decoration we should do
    """
    pr_billing_whitelisted_owners = [
        int(ownerid.strip())
        for ownerid in os.getenv("PR_AUTHOR_BILLING_WHITELISTED_OWNERS", "").split()
    ]

    if enriched_pull:
        db_pull = enriched_pull.database_pull
        provider_pull = enriched_pull.provider_pull

        org = db_pull.repository.owner

        if not (
            org.plan in ["users-inappm-pr", "users-inappy-pr"]
            and org.ownerid in pr_billing_whitelisted_owners
        ):
            return Decoration.standard

        if db_pull.repository.private is not False:
            # public repo or repo we arent certain is private should be standard
            return Decoration.standard

        db_session = commit.get_db_session()

        pr_author = (
            db_session.query(Owner)
            .filter(
                Owner.service == org.service, Owner.service_id == db_pull.author.id,
            )
            .first()
        )

        if not pr_author:
            log.warning(
                "PR author not found in database",
                extra=dict(
                    author_service=org.service,
                    author_service_id=db_pull.author.id,
                    author_username=db_pull.author.username,
                ),
            )
            return Decoration.standard

        is_pr_author_org_member = pr_author.ownerid in org.plan_activated_users
        if not is_pr_author_org_member and org.plan_auto_activate:
            log.info(
                "Attempting PR author auto activation",
                extra=dict(
                    org_ownerid=org.ownerid,
                    author_ownerid=pr_author.ownerid,
                    pullid=db_pull.pullid,
                ),
            )
            activation_success = db.session.query(
                func.public.try_to_auto_activate(org.ownerid, pr_author.ownerid)
            ).all()

            if not activation_success:
                log.info(
                    "PR author auto activation was not successful",
                    extra=dict(
                        org_ownerid=org.ownerid,
                        author_ownerid=pr_author.ownerid,
                        pullid=db_pull.pullid,
                    ),
                )
                return Decoration.upgrade
            
            # TODO: activation was successful so we should run the future NewUserActivatedTask
        else:
            return Decoration.upgrade

    return Decoration.standard
