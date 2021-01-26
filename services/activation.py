import logging
from sqlalchemy import func
from sqlalchemy.sql import text
from services.license import get_current_license, calculate_reason_for_not_being_valid, requires_license

log = logging.getLogger(__name__)


def activate_user(db_session, org_ownerid: int, user_ownerid: int) -> bool:
    """
    Attempt to activate the user for the given org

    Returns:
        bool: was the user successfully activated
    """

    log.info(
        "Checking the environment", extra=dict(requires_license=requires_license())
    )

    if requires_license():
        # we will not activate if the license is invalid for any reason.
        license_status = calculate_reason_for_not_being_valid(db_session)
        if license_status is None:
            # check if you have an available seat with which to activate.
            query_string = text(
                """
                        WITH all_plan_activated_users AS (
                            SELECT 
                                UNNEST(o.plan_activated_users) AS activated_owner_id
                            FROM owners o
                        ) SELECT count(*) as count
                        FROM all_plan_activated_users"""
            )
            seat_query = db_session.execute(query_string).fetchall()

            can_activate = True
            for result in seat_query:
                if result[0] >= get_current_license().number_allowed_users:
                    can_activate = False
            # add user_ownerid to orgs, plan activated users.
            if can_activate: 
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
                ).fetchall()
            else:
                log.info(
                "Auto activation failed due to no seats remaining",
                extra=dict(
                    org_ownerid=org_ownerid,
                    author_ownerid=user_ownerid,
                    activation_success=False,
                    license_status=license_status,
                ),
            )
            return False


        else:
            log.info(
                "Auto activation failed due to invalid license",
                extra=dict(
                    org_ownerid=org_ownerid,
                    author_ownerid=user_ownerid,
                    activation_success=False,
                    license_status=license_status,
                ),
            )
            return False

        log.info(
            "Enterprise PR Auto activation attempted",
            extra=dict(
                org_ownerid=org_ownerid,
                author_ownerid=user_ownerid,
                activation_success=activation_success,
            ),
        )

        return True

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
