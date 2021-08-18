# http://docs.celeryq.org/en/latest/configuration.html#configuration
import logging
import logging.config

from celery import signals
from celery.beat import BeatLazyFunc
from celery.schedules import crontab
from shared.celery_config import BaseCeleryConfig

from helpers.cache import RedisBackend, cache
from helpers.clock import get_utc_now_as_iso_format
from services.redis import get_redis_connection

log = logging.getLogger(__name__)


@signals.setup_logging.connect
def initialize_logging(loglevel=logging.INFO, **kwargs):
    celery_logger = logging.getLogger("celery")
    celery_logger.setLevel(loglevel)
    log.info("Initialized celery logging")
    return celery_logger


@signals.worker_process_init.connect
def initialize_cache(**kwargs):
    log.info("Initialized cache")
    redis_cache_backend = RedisBackend(get_redis_connection())
    cache.configure(redis_cache_backend)


hourly_check_task_name = "app.cron.hourly_check.HourlyCheckTask"
find_uncollected_profilings_task_name = (
    "app.cron.profiling.FindUncollectedProfilingsTask"
)


class CeleryWorkerConfig(BaseCeleryConfig):
    beat_schedule = {
        "hourly_check": {
            "task": hourly_check_task_name,
            "schedule": crontab(minute="0"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        },
        "find_uncollected_profilings": {
            "task": find_uncollected_profilings_task_name,
            "schedule": crontab(minute="0"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        },
    }
