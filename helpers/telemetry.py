import asyncio
from datetime import datetime

from shared.django_apps.pg_telemetry.models import SimpleMetric as PgSimpleMetric
from shared.django_apps.ts_telemetry.models import SimpleMetric as TsSimpleMetric

from database.engine import get_db_session
from database.models.core import Commit, Owner, Repository


class fire_and_forget:
    background_tasks = set()

    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *args, **kwargs):
        print(self, *args, **kwargs)
        task = asyncio.create_task(self.fn(*args, **kwargs))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)


class MetricContext:
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
            f"{owner_slug}/{repo.name}" if self.owner_slug and repo else None
        )
        self.commit_slug = (
            f"{repo_slug}/{commit.commitid}" if self.repo_slug and commit else None
        )

        dbsession.close()
        self.populated = True

    def log_simple_metric(self, name: str, value: float):
        timestamp = datetime.now()

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
