import logging

from shared.celery_config import (
    activate_account_user_task_name,
    new_user_activated_task_name,
)
from sqlalchemy import func
from sqlalchemy.sql import text

from app import celery_app
from services.license import (
    calculate_reason_for_not_being_valid,
    get_current_license,
    get_installation_plan_activated_users,
    requires_license,
)

log = logging.getLogger(__name__)


def activate_user(db_session, org_ownerid: int, user_ownerid: int) -> bool:
    """
    Attempt to activate the user for the given org

    Returns:
        bool: was the user successfully activated
    """
    if requires_license():
        # we will not activate if the license is invalid for any reason.
        license_status = calculate_reason_for_not_being_valid(db_session)
        if license_status is None:
            # check if you have an available seat with which to activate.
            seat_query = get_installation_plan_activated_users(db_session)

            this_license = get_current_license()
            can_activate = all(
                result[0] < this_license.number_allowed_users for result in seat_query
            )
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
                    query_string,
                    {"user_ownerid": user_ownerid, "org_ownerid": org_ownerid},
                ).fetchall()

                log.info(
                    "PR Auto activation attempted",
                    extra=dict(
                        org_ownerid=org_ownerid,
                        author_ownerid=user_ownerid,
                        activation_success=activation_success,
                    ),
                )

                return True
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


def schedule_new_user_activated_task(self, org_ownerid, user_ownerid):
    celery_app.send_task(
        new_user_activated_task_name,
        args=None,
        kwargs=dict(org_ownerid=org_ownerid, user_ownerid=user_ownerid),
    )
    # Activate the account user if it exists.
    celery_app.send_task(
        activate_account_user_task_name,
        args=None,
        kwargs=dict(
            user_ownerid=user_ownerid,
            org_ownerid=org_ownerid,
        ),
    )
