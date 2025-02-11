import logging

from shared.plan.constants import PlanName

from app import celery_app
from celery_config import trial_expiration_cron_task_name, trial_expiration_task_name
from database.enums import TrialStatus
from database.models.core import Owner
from helpers.clock import get_utc_now
from tasks.crontasks import CodecovCronTask

log = logging.getLogger(__name__)

yield_amount = 100


class TrialExpirationCronTask(CodecovCronTask, name=trial_expiration_cron_task_name):
    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 86100  # 23 hours and 55 minutes

    def run_cron_task(self, db_session, *args, **kwargs):
        log.info("Doing trial expiration check")
        now = get_utc_now()

        ongoing_trial_owners_that_should_be_expired = (
            db_session.query(Owner.ownerid)
            .filter(
                Owner.plan == PlanName.TRIAL_PLAN_NAME.value,
                Owner.trial_status == TrialStatus.ONGOING.value,
                Owner.trial_end_date <= now,
            )
            .yield_per(yield_amount)
        )

        for owner in ongoing_trial_owners_that_should_be_expired:
            self.app.tasks[trial_expiration_task_name].apply_async(
                kwargs=dict(ownerid=owner.ownerid)
            )

        return {"successful": True}


RegisteredTrialExpirationCronTask = celery_app.register_task(TrialExpirationCronTask())
trial_expiration_cron_task = celery_app.tasks[RegisteredTrialExpirationCronTask.name]
