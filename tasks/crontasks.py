import logging
from datetime import datetime, timedelta, timezone

from redis.exceptions import LockError

from services.redis import get_redis_connection
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class CodecovCronTask(BaseCodecovTask):
    @classmethod
    def get_min_seconds_interval_between_executions(cls) -> int:
        """
        Ensures the task never runs twice inside a certain time interval.

        This is just a mechanism of protection in addition to the lock.
            The lock guarantees two tasks don't run at the same time in case
            they are scheduled by two different workers. But if one task finishes
            too quickly before the other one even starts (due to queue timing),
            they will both run.

        So this task gives a little buffer on that. So if a task is meant to run
            every hour or so, giving it a 50-55 minutes buffer ensure that the tasks
            coming right after it won't run (unless there is some crazy queue that makes
            a task take 50 minute to run) while still making sure the task arriving
            on the next hour can still run

        Returns:
            int: Number of seconds to wait before the task is run again
        """
        raise NotImplementedError()

    def run_impl(self, db_session, *args, cron_task_generation_time_iso, **kwargs):
        lock_name = f"worker.executionlock.{self.name}"
        redis_connection = get_redis_connection()
        generation_time = datetime.fromisoformat(cron_task_generation_time_iso)
        try:
            with redis_connection.lock(
                lock_name,
                timeout=max(60 * 5, self.hard_time_limit_task),
                blocking_timeout=1,
            ):
                min_seconds_interval = (
                    self.get_min_seconds_interval_between_executions()
                )
                last_executed_key = f"worker.last_execution_on.{self.name}"
                last_execution_on = redis_connection.get(last_executed_key)
                if last_execution_on is not None and generation_time - timedelta(
                    seconds=min_seconds_interval
                ) < datetime.fromtimestamp(
                    int(float(last_execution_on)), tz=timezone.utc
                ):
                    log.info("Cron task executed very recently. Skipping")
                    return {"executed": False}
                redis_connection.setex(
                    last_executed_key, min_seconds_interval, generation_time.timestamp()
                )
                log.info("Executing cron task")
                result = self.run_cron_task(db_session, *args, **kwargs)
                return {"executed": True, "result": result}
        except LockError:
            log.info("Not executing cron task since another one is already running it")
            return {"executed": False}
