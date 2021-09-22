# http://docs.celeryq.org/en/latest/configuration.html#configuration
import logging
import logging.config
import os
import re

from celery import signals
from celery.beat import BeatLazyFunc
from celery.schedules import crontab
from celery.signals import worker_process_init
from codecovopentelem import get_codecov_opentelemetry_instances
from opentelemetry import trace
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from shared.celery_config import BaseCeleryConfig, profiling_finding_task_name

from helpers.cache import RedisBackend, cache
from helpers.clock import get_utc_now_as_iso_format
from helpers.environment import is_enterprise
from helpers.version import get_current_version
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


@worker_process_init.connect(weak=False)
def init_celery_tracing(*args, **kwargs):
    if (
        os.getenv("OPENTELEMETRY_ENDPOINT")
        and os.getenv("OPENTELEMETRY_TOKEN")
        and os.getenv("OPENTELEMETRY_CODECOV_RATE")
        and not is_enterprise()
    ):
        log.info("Configuring opentelemetry exporter")
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        generator, exporter = get_codecov_opentelemetry_instances(
            repository_token=os.getenv("OPENTELEMETRY_TOKEN"),
            profiling_identifier=get_current_version(),
            sample_rate=float(os.getenv("OPENTELEMETRY_CODECOV_RATE")),
            name_regex=re.compile("run/.*"),
            codecov_endpoint=os.getenv("OPENTELEMETRY_ENDPOINT"),
            writeable_folder="/home/codecov",
        )
        provider.add_span_processor(generator)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        CeleryInstrumentor().instrument()


hourly_check_task_name = "app.cron.hourly_check.HourlyCheckTask"


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
            "task": profiling_finding_task_name,
            "schedule": crontab(minute="0,30"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        },
    }
