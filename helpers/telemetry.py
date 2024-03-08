import asyncio
from datetime import datetime

import django
from shared.django_apps.pg_telemetry.models import SimpleMetric as PgSimpleMetric
from shared.django_apps.ts_telemetry.models import SimpleMetric as TsSimpleMetric

from database.engine import get_db_session
from database.models.core import Commit, Owner, Repository


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


class MetricContext:
    """
    Timeseries metrics can be tagged with context (repo, commit, owner) and this
    class holds onto that context. It exposes a way to log timeseries metrics
    with context appended.

    Create it with whatever context you've got (e.g. IDs that were passed in as
    task arguments) and it will attempt to fetch the rest before logging for the
    first time.

    `log_simple_metric()` will call `populate()` if it hasn't been called before
    and then log a simple metric with the pass-in name/value to both Postgres
    and Timescale. This function is synchronous/blocking.

    `attempt_log_simple_metric()` is the @fire_and_forget version of
    `log_simple_metric()`, meaning it will throw populating/logging on the
    asyncio queue and then immediately return without needing to be awaited. Can
    only be used in an event loop/async function.
    """

    def __init__(
        self,
        repo_id: int = None,
        owner_id: int = None,
        commit_id: int = None,
        commit_sha: str = None,
    ):
        self.repo_id = repo_id
        self.commit_id = commit_id
        self.commit_sha = commit_sha
        self.owner_id = owner_id
        self.repo_slug = None
        self.owner_slug = None
        self.commit_slug = None
        self.populated = False

    def populate(self):
        if self.populated:
            return

        repo = None
        owner = None
        commit = None
        dbsession = get_db_session()

        if self.repo_id:
            repo = (
                dbsession.query(Repository)
                .filter(Repository.repoid == self.repo_id)
                .first()
            )
            owner = repo.owner
            if not self.owner_id:
                self.owner_id = owner.ownerid

            if self.commit_sha:
                commit = (
                    dbsession.query(Commit)
                    .filter(
                        Commit.repoid == self.repo_id,
                        Commit.commitid == self.commit_sha,
                    )
                    .first()
                )
                self.commit_id = commit.id_
        elif self.owner_id:
            owner = (
                dbsession.query(Owner).filter(Owner.ownerid == self.owner_id).first()
            )

        self.owner_slug = f"{owner.service}/{owner.username}" if owner else None
        self.repo_slug = (
            f"{self.owner_slug}/{repo.name}" if self.owner_slug and repo else None
        )
        self.commit_slug = (
            f"{self.repo_slug}/{commit.commitid}" if self.repo_slug and commit else None
        )

        self.populated = True

    def log_simple_metric(self, name: str, value: float):
        # Timezone-aware timestamp in UTC
        timestamp = django.utils.timezone.now()

        self.populate()

        PgSimpleMetric.objects.create(
            timestamp=timestamp,
            name=name,
            value=value,
            repo_id=self.repo_id,
            owner_id=self.owner_id,
            commit_id=self.commit_id,
        )

        TsSimpleMetric.objects.create(
            timestamp=timestamp,
            name=name,
            value=value,
            repo_slug=self.repo_slug,
            owner_slug=self.owner_slug,
            commit_slug=self.commit_slug,
        )

    @fire_and_forget
    async def attempt_log_simple_metric(self, name: str, value: float):
        self.log_simple_metric(name, value)


class TimeseriesTimer:
    """
    Timer class that create timeseries metrics. Used as a context manager:

    metric_context = MetricContext(
        repo_id=kwargs['repoid'],
        owner_id=kwargs['ownerid'],
        commit_sha=kwargs['commitid'],
    )
    with TimeseriesTimer(metric_context, "metric_name"):
        run_task(...)
    """

    def __init__(self, metric_context: MetricContext, name: str, sync=False):
        self.metric_context = metric_context
        self.name = name
        self.sync = sync

    def __enter__(self):
        self.start_time = datetime.now()

    def __exit__(self, *exc):
        end_time = datetime.now()
        delta = end_time - self.start_time

        if self.sync:
            self.metric_context.log_simple_metric(self.name, delta.total_seconds())
        else:
            self.metric_context.attempt_log_simple_metric(
                self.name, delta.total_seconds()
            )
