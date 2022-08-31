import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app import celery_app
from celery_config import daily_plan_manager_task_name
from database.models.core import OrganizationLevelToken, Owner
from helpers.metrics import metrics
from services.billing import BillingPlan
from tasks.crontasks import CodecovCronTask

log = logging.getLogger(__name__)


class DailyPlanManagerTask(CodecovCronTask):
    PLANS_THAT_CAN_HAVE_ORG_LEVEL_TOKENS = [
        BillingPlan.enterprise_cloud_monthly.value,
        BillingPlan.enterprise_cloud_yearly.value,
    ]

    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 86100  # 1 day - 5 minutes

    # TODO: Move to shared (celery_config)
    name = daily_plan_manager_task_name

    async def run_cron_task(self, db_session: Session, *args, **kwargs):
        # Query all org-wide tokens
        tokens_to_delete = (
            db_session.query(OrganizationLevelToken.id_)
            .join(Owner)
            .filter(Owner.plan.notin_(self.PLANS_THAT_CAN_HAVE_ORG_LEVEL_TOKENS))
        )
        log.info(
            "Deleting OrganizationLevelTokens that belong to invalid plans",
            extra=dict(deleted_tokens_ids=tokens_to_delete.all()),
        )
        deleted_count = (
            db_session.query(OrganizationLevelToken)
            .filter(OrganizationLevelToken.id_.in_(tokens_to_delete.subquery()))
            .delete(synchronize_session=False)
        )
        db_session.commit()
        return dict(checked=True, deleted=deleted_count)


RegistedDailyPlanManagerTask = celery_app.register_task(DailyPlanManagerTask())
daily_plan_manager_task = celery_app.tasks[RegistedDailyPlanManagerTask.name]
