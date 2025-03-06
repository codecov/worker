import logging

from shared.celery_config import activate_account_user_task_name
from shared.django_apps.codecov_auth.models import Account, Owner
from sqlalchemy.orm.session import Session

from app import celery_app
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ActivateAccountUserTask(BaseCodecovTask, name=activate_account_user_task_name):
    def run_impl(
        self,
        _db_session: Session,
        *,
        user_ownerid: int,
        org_ownerid: int,
        **kwargs,
    ):
        """
        Runs the task to activate a user onto an account.
        :param user_ownerid: the user's owner id
        :param org_ownerid: the organization owner id
        """
        log_context = {"user_ownerid": user_ownerid, "org_ownerid": org_ownerid}
        log.info(
            "Syncing account for user",
            extra=log_context,
        )

        owner_user: Owner = Owner.objects.get(pk=user_ownerid)

        # NOTE: We're currently ignoring organizations that don't have an account.
        org_owner: Owner = Owner.objects.get(pk=org_ownerid)
        account: Account | None = org_owner.account
        if not account:
            log.info(
                "Organization does not have an account. Skipping account user activation."
            )
            return {"successful": True}

        if account.can_activate_user(owner_user.user):
            account.activate_owner_user_onto_account(owner_user)
            account.save()
        else:
            log.info(
                "User was not able to activate on account. It could be that the user is already activated, "
                "or the account is in an inconsistent state.",
                extra=log_context,
            )

        log.info(
            "Successfully synced account for user",
            extra=log_context,
        )

        return {"successful": True}


RegisteredActivateAccountUserTask = celery_app.register_task(ActivateAccountUserTask())
activate_account_user_task = celery_app.tasks[ActivateAccountUserTask.name]
