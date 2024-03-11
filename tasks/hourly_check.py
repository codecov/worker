import logging

from app import celery_app
from celery_config import hourly_check_task_name
from helpers.metrics import metrics
from tasks.crontasks import CodecovCronTask

log = logging.getLogger(__name__)


class HourlyCheckTask(CodecovCronTask, name=hourly_check_task_name):
    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 3300  # 55 minutes

    def run_cron_task(self, db_session, *args, **kwargs):
        log.info("Doing hourly check")
        metrics.incr(f"{self.metrics_prefix}.checks")
        return {"checked": True}


RegisteredHourlyCheckTask = celery_app.register_task(HourlyCheckTask())
hourly_check_task = celery_app.tasks[RegisteredHourlyCheckTask.name]
