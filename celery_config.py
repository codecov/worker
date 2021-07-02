# http://docs.celeryq.org/en/latest/configuration.html#configuration
import logging

import logging.config

from helpers.cache import cache, RedisBackend
from services.redis import get_redis_connection

from shared.celery_config import BaseCeleryConfig
from celery import signals

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


class CeleryWorkerConfig(BaseCeleryConfig):
    pass
