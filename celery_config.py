# http://docs.celeryq.org/en/latest/configuration.html#configuration
import gc
import logging
import logging.config
from datetime import timedelta

from celery import signals
from celery.beat import BeatLazyFunc
from celery.schedules import crontab
from shared.celery_config import (
    BaseCeleryConfig,
    brolly_stats_rollup_task_name,
    flare_cleanup_task_name,
    gh_app_webhook_check_task_name,
    health_check_task_name,
    profiling_finding_task_name,
)
from shared.config import get_config
from shared.helpers.cache import RedisBackend

from celery_task_router import route_task
from helpers.cache import cache
from helpers.clock import get_utc_now_as_iso_format
from helpers.health_check import get_health_check_interval_seconds
from services.redis import get_redis_connection

log = logging.getLogger(__name__)


@signals.worker_before_create_process.connect
def prefork_gc_freeze(**kwargs) -> None:
    # This comes from https://github.com/getsentry/sentry/pull/63001
    # More info https://www.youtube.com/watch?v=Hgw_RlCaIds
    # The idea is to save memory in the worker subprocesses
    # By freezing all the stuff we can just read from
    gc.freeze()


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
daily_plan_manager_task_name = "app.cron.daily.PlanManagerTask"

notify_error_task_name = "app.tasks.notify.NotifyErrorTask"

# Backfill GH Apps
backfill_existing_gh_app_installations_name = "app.tasks.backfill_existing_gh_app_installations.BackfillExistingGHAppInstallationsTask"
backfill_existing_individual_gh_app_installation_name = "app.tasks.backfill_existing_individual_gh_app_installation.BackfillExistingIndividualGHAppInstallationTask"
backfill_owners_without_gh_app_installations_name = "app.tasks.backfill_owners_without_gh_app_installations.BackfillOwnersWithoutGHAppInstallationsTask"
backfill_owners_without_gh_app_installation_individual_name = "app.tasks.backfill_owners_without_gh_app_installation_individual.BackfillOwnersWithoutGHAppInstallationIndividualTask"

trial_expiration_task_name = "app.tasks.plan.TrialExpirationTask"
trial_expiration_cron_task_name = "app.cron.plan.TrialExpirationCronTask"

update_branches_task_name = "app.cron.branches.UpdateBranchesTask"
update_branches_task_name = "app.cron.test_instances.BackfillTestInstancesTask"

cache_rollup_cron_task_name = "app.cron.cache_rollup.CacheRollupTask"


def _beat_schedule():
    beat_schedule = {
        "hourly_check": {
            "task": hourly_check_task_name,
            "schedule": crontab(minute="0"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        },
        "github_app_webhooks_task": {
            "task": gh_app_webhook_check_task_name,
            "schedule": crontab(minute="0", hour="0,6,12,18"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        },
        "trial_expiration_cron": {
            "task": trial_expiration_cron_task_name,
            # 4 UTC is 12am EDT
            "schedule": crontab(minute="0", hour="4"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        },
        "flare_cleanup": {
            "task": flare_cleanup_task_name,
            "schedule": crontab(minute="0", hour="4"),  # every day, 4am UTC (8pm PT)
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        },
    }

    if get_config("setup", "find_uncollected_profilings", "enabled", default=True):
        beat_schedule["find_uncollected_profilings"] = {
            "task": profiling_finding_task_name,
            "schedule": crontab(minute="0,15,30,45"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        }

    if get_config("setup", "health_check", "enabled", default=False):
        beat_schedule["health_check_task"] = {
            "task": health_check_task_name,
            "schedule": timedelta(seconds=get_health_check_interval_seconds()),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        }

    if get_config("setup", "telemetry", "enabled", default=True):
        beat_schedule["brolly_stats_rollup"] = {
            "task": brolly_stats_rollup_task_name,
            "schedule": crontab(minute="0", hour="2"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        }

    if get_config("setup", "cache_rollup", "enabled", default=False):
        beat_schedule["cache_rollup"] = {
            "task": cache_rollup_cron_task_name,
            "schedule": crontab(minute="0", hour="2"),
            "kwargs": {
                "cron_task_generation_time_iso": BeatLazyFunc(get_utc_now_as_iso_format)
            },
        }

    return beat_schedule


class CeleryWorkerConfig(BaseCeleryConfig):
    beat_schedule = _beat_schedule()

    task_routes = route_task
