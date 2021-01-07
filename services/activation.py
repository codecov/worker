import logging
from sqlalchemy import func
from sqlalchemy.sql import text
from services.license import calculate_reason_for_not_being_valid
from helpers.environment import is_enterprise

log = logging.getLogger(__name__)


def activate_user(db_session, org_ownerid: int, user_ownerid: int) -> bool:
    """
    Attempt to activate the user for the given org

    Returns:
        bool: was the user successfully activated
    """

    if is_enterprise():
        # we will not activate if the license is invalid for any reason.
        if calculate_reason_for_not_being_valid() is None:
            # add user_ownerid to orgs, plan activated users.
            query_string = text(
                """
                          UPDATE owners
                                        set plan_activated_users = array_append_unique(plan_activated_users, :user_ownerid)
                                        where ownerid=:org_ownerid
                                        returning ownerid, 
                                        plan_activated_users, 
                                        username, 
                                        plan_activated_users @> array[:user_ownerid]::int[] as has_access;"""
            )
            (activation_success,) = db_session.execute(
                query_string, {"user_ownerid": user_ownerid, "org_ownerid": org_ownerid}
            ).first()

        else:
            log.info(
                "Auto activation failed due to invalid license",
                extra=dict(
                    org_ownerid=org_ownerid,
                    author_ownerid=user_ownerid,
                    activation_success=False,
                ),
            )
            return False

        log.info(
            "Enterprose PR Auto activation attempted",
            extra=dict(
                org_ownerid=org_ownerid,
                author_ownerid=user_ownerid,
                activation_success=activation_success,
            ),
        )

        return activation_success

    # TODO: we need to decide the best way for this logic to be shared across
    # worker and codecov-api - ideally moving logic from database to application layer
    (activation_success,) = db_session.query(
        func.public.try_to_auto_activate(org_ownerid, user_ownerid)
    ).first()

    log.info(
        "Auto activation attempted",
        extra=dict(
            org_ownerid=org_ownerid,
            author_ownerid=user_ownerid,
            activation_success=activation_success,
        ),
    )
    return activation_success
