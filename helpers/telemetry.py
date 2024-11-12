import asyncio
import logging
from datetime import datetime

import django
from asgiref.sync import sync_to_async
from shared.django_apps.pg_telemetry.models import SimpleMetric as PgSimpleMetric

from helpers.log_context import get_log_context

log = logging.getLogger(__name__)


def fire_and_forget(fn):
    """
    Decorator for an async function that will throw it in the asyncio queue and
    return immediately. The caller does not need to await the result.

    Useful for things like telemetry where you don't want to delay the actual
    logic too long for it and it's not the worst thing if it fails.
    """
    if not hasattr(fire_and_forget, "background_tasks"):
        fire_and_forget.background_tasks = set()

    def wrapper(*args, **kwargs):
        task = asyncio.create_task(fn(*args, **kwargs))
        fire_and_forget.background_tasks.add(task)
        task.add_done_callback(fire_and_forget.background_tasks.discard)

    return wrapper


@sync_to_async
def log_simple_metric_async(name: str, value: float):
    log_simple_metric(name, value)


def log_simple_metric(name: str, value: float):
    """
    `log_simple_metric()` will get metadata values from the log context
    and then log a simple metric with the pass-in name/value to Postgres.
    This function is synchronous/blocking.
    """

    # Timezone-aware timestamp in UTC
    timestamp = django.utils.timezone.now()

    log_context = get_log_context()

    try:
        PgSimpleMetric.objects.create(
            timestamp=timestamp,
            name=name,
            value=value,
            repo_id=log_context.repo_id,
            owner_id=log_context.owner_id,
            commit_id=log_context.commit_id,
        )
    except Exception:
        log.exception("Failed to create telemetry_simple record")


@fire_and_forget
async def attempt_log_simple_metric(name: str, value: float):
    """
    `attempt_log_simple_metric()` is the @fire_and_forget version of
    `log_simple_metric()`, meaning it will throw logging on the
    asyncio queue and then immediately return without needing to be awaited. Can
    only be used in an event loop/async function.
    """
    await log_simple_metric_async(name, value)


class TimeseriesTimer:
    """
    Timer class that create timeseries metrics. Used as a context manager:

    with TimeseriesTimer("metric_name"):
        run_task(...)
    """

    def __init__(self, name: str, sync=False):
        self.name = name
        self.sync = sync

    def __enter__(self):
        self.start_time = datetime.now()

    def __exit__(self, *exc):
        end_time = datetime.now()
        delta = end_time - self.start_time

        if self.sync:
            log_simple_metric(self.name, delta.total_seconds())
        else:
            attempt_log_simple_metric(self.name, delta.total_seconds())
