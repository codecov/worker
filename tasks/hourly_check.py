import logging

from tasks.crontasks import CodecovCronTask
from helpers.metrics import metrics
from celery_config import hourly_check_task_name
from app import celery_app

log = logging.getLogger(__name__)


class HourlyCheckTask(CodecovCronTask):
    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 3300  # 55 minutes

    name = hourly_check_task_name

    async def run_cron_task(self, db_session, *args, **kwargs):
        log.info("Doing hourly check")
        metrics.incr(f"{self.metrics_prefix}.checks")
        return {"checked": True}


RegisteredHourlyCheckTask = celery_app.register_task(HourlyCheckTask())
hourly_check_task = celery_app.tasks[RegisteredHourlyCheckTask.name]
