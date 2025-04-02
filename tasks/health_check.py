import logging
from typing import Set

import shared.helpers.redis as redis_service
from shared.celery_config import health_check_task_name
from shared.config import get_config

from app import celery_app
from helpers.metrics import metrics
from tasks.crontasks import CodecovCronTask

log = logging.getLogger(__name__)


class HealthCheckTask(CodecovCronTask, name=health_check_task_name):
    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 8  # This task should run every 10s, so this time should be small.

    def _get_all_queue_names_from_config(self) -> Set[str]:
        """
        Gets all queue names defined in the *install* codecov.yaml.
        EXCEPT the healthcheck queue itself that's hardcoded in celery_config.py.
        """
        tasks_config = get_config("setup", "tasks", default={})
        default_queue_name = get_config(
            "setup", "tasks", "celery", "default_queue", default="celery"
        )
        queue_names_in_config = set(
            [
                item["queue"]
                for _, item in tasks_config.items()
                if item.get("queue") is not None
            ]
        )
        queue_names_in_config.add(default_queue_name)
        enterprise_queues = set(
            map(lambda queue: "enterprise_" + queue, queue_names_in_config)
        )
        return queue_names_in_config | enterprise_queues

    def _get_correct_redis_connection(self):
        if get_config("services", "celery_broker"):
            return redis_service._get_redis_instance_from_url(
                get_config("services", "celery_broker")
            )
        else:
            return redis_service.get_redis_connection()

    def run_cron_task(self, db_session, *args, **kwargs):
        queue_names = self._get_all_queue_names_from_config()
        redis = self._get_correct_redis_connection()
        for q in queue_names:
            metrics.gauge("celery.queue.%s.len" % q, redis.llen(q))


RegisteredHealthCheckTask = celery_app.register_task(HealthCheckTask())
health_check_task = celery_app.tasks[RegisteredHealthCheckTask.name]
