import logging

from app import celery_app
from celery_config import trial_expiration_task_name
from database.enums import TrialStatus
from database.models.core import Owner
from services.billing import BillingPlan
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class TrialExpirationTask(BaseCodecovTask):
    name = trial_expiration_task_name

    async def run_async(self, db_session, ownerid, *args, **kwargs):
        owner = db_session.query(Owner).get(ownerid)
        log_extra = dict(
            owner_id=ownerid,
            trial_end_date=owner.trial_end_date,
        )
        log.info(
            "Expiring owner's trial and setting back to basic plan", extra=log_extra
        )
        owner.plan = BillingPlan.users_basic.value
        owner.plan_activated_users = None
        owner.plan_user_count = 1
        owner.stripe_subscription_id = None
        owner.trial_status = TrialStatus.EXPIRED.value
        db_session.add(owner)
        db_session.flush()
        return {"successful": True}


RegisteredTrialExpirationTask = celery_app.register_task(TrialExpirationTask())
trial_expiration_task = celery_app.tasks[RegisteredTrialExpirationTask.name]
