import logging

from shared.django_apps.codecov_auth.models import Owner
from shared.plan.service import PlanService

from app import celery_app
from celery_config import trial_expiration_task_name
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class TrialExpirationTask(BaseCodecovTask, name=trial_expiration_task_name):
    def run_impl(self, db_session, ownerid, *args, **kwargs):
        owner = Owner.objects.get(ownerid=ownerid)
        log_extra = dict(
            owner_id=ownerid,
            trial_end_date=owner.trial_end_date,
        )
        log.info(
            "Expiring owner's trial and setting back to basic plan", extra=log_extra
        )
        owner_plan = PlanService(current_org=owner)
        owner_plan.cancel_trial()
        return {"successful": True}


RegisteredTrialExpirationTask = celery_app.register_task(TrialExpirationTask())
trial_expiration_task = celery_app.tasks[RegisteredTrialExpirationTask.name]
