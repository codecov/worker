import logging
from typing import List, Mapping

from shared.torngit.exceptions import TorngitRateLimitError

from app import celery_app
from celery_config import trial_expiration_task_name
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
        try:
            owner.plan = BillingPlan.users_basic.value
            owner.plan_activated_users = None
            owner.plan_user_count = 1
            owner.stripe_subscription_id = None
            db_session.add(owner)
            db_session.flush()
        except Exception as e:
            log.warning(
                "Unable to expire owner trial",
                extra=dict(
                    comparison_id=ownerid,
                ),
                exc_info=True,
            )
            return {"successful": False}
        return {"successful": True}


RegisteredTrialExpirationTask = celery_app.register_task(TrialExpirationTask())
trial_expiration_task = celery_app.tasks[RegisteredTrialExpirationTask.name]
