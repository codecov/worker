import logging
from datetime import datetime
from typing import Iterable

from celery import group
from celery.canvas import Signature
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Commit, Repository
from database.models.timeseries import Dataset
from helpers.timeseries import timeseries_enabled
from services.timeseries import (
    repository_commits_query,
    repository_datasets_query,
    save_commit_measurements,
    save_repository_measurements,
)
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class TimeseriesBackfillTask(BaseCodecovTask):

    # TODO: add name to `shared.celery_config`
    name = "app.tasks.timeseries.backfill"

    async def run_async(
        self,
        db_session: Session,
        *,
        repoid: int,
        start_date: str,
        end_date: str,
        dataset_names: Iterable[str] = None,
        **kwargs,
    ):
        repository = db_session.query(Repository).filter_by(repoid=repoid).first()
        if not repository:
            log.error(
                "Repository not found",
                extra=dict(repoid=repoid),
            )
            return {"successful": False}

        try:
            start_date = datetime.fromisoformat(start_date)
            end_date = datetime.fromisoformat(end_date)
            if dataset_names is None:
                datasets = repository_datasets_query(repository, backfilled=False)
                dataset_names = [dataset.name for dataset in datasets]
            save_repository_measurements(
                repository,
                start_date,
                end_date,
                dataset_names=dataset_names,
            )
            return {"successful": True}
        except ValueError:
            log.error(
                "Invalid date range",
                extra=dict(start_date=start_date, end_date=end_date),
            )
            return {"successful": False}


RegisteredTimeseriesBackfillTask = celery_app.register_task(TimeseriesBackfillTask())
timeseries_backfill_task = celery_app.tasks[RegisteredTimeseriesBackfillTask.name]


class TimeseriesBackfillCommitsTask(BaseCodecovTask):

    # TODO: add name to `shared.celery_config`
    name = "app.tasks.timeseries.backfill_commits"

    async def run_async(
        self,
        db_session: Session,
        *,
        commit_ids: Iterable[int],
        dataset_names: Iterable[str],
        **kwargs,
    ):
        if not timeseries_enabled():
            log.warning("Timeseries not enabled")
            return {"successful": False}

        commits = db_session.query(Commit).filter(Commit.id_.in_(commit_ids))
        for commit in commits:
            save_commit_measurements(commit, dataset_names=dataset_names)
        return {"successful": True}


RegisteredTimeseriesBackfillCommitsTask = celery_app.register_task(
    TimeseriesBackfillCommitsTask()
)
timeseries_backfill_commits_task = celery_app.tasks[
    RegisteredTimeseriesBackfillCommitsTask.name
]


class TimeseriesBackfillDatasetTask(BaseCodecovTask):

    # TODO: add name to `shared.celery_config`
    name = "app.tasks.timeseries.backfill_dataset"

    async def run_async(
        self,
        db_session: Session,
        *,
        dataset_id: int,
        start_date: str,
        end_date: str,
        batch_size: int = 100,
        **kwargs,
    ):
        if not timeseries_enabled():
            log.warning("Timeseries not enabled")
            return {"successful": False}

        dataset = db_session.query(Dataset).filter(Dataset.id_ == dataset_id).first()
        if not dataset:
            log.error(
                "Dataset not found",
                extra=dict(dataset_id=dataset_id),
            )
            return {"successful": False}

        repository = (
            db_session.query(Repository).filter_by(repoid=dataset.repository_id).first()
        )
        if not repository:
            log.error(
                "Repository not found",
                extra=dict(repoid=dataset.repository_id),
            )
            return {"successful": False}

        try:
            start_date = datetime.fromisoformat(start_date)
            end_date = datetime.fromisoformat(end_date)
        except ValueError:
            log.error(
                "Invalid date range",
                extra=dict(start_date=start_date, end_date=end_date),
            )
            return {"successful": False}

        # all commits in given time range
        commits = repository_commits_query(repository, start_date, end_date)

        # split commits into batches of equal size
        signatures = self._commit_batch_signatures(dataset, commits, batch_size)

        # enqueue task for each batch (to be run in parallel)
        group(signatures).apply_async()

        return {"successful": True}

    def _commit_batch_signatures(
        self, dataset: Dataset, commits: Iterable[Commit], batch_size: int
    ) -> Iterable[Signature]:
        commit_ids = []
        signatures = []
        for commit in commits:
            if len(commit_ids) == batch_size:
                signatures.append(self._backfill_commits_signature(dataset, commit_ids))
                commit_ids = []
            commit_ids.append(commit.id_)
        if len(commit_ids) > 0:
            signatures.append(self._backfill_commits_signature(dataset, commit_ids))
        return signatures

    def _backfill_commits_signature(
        self, dataset: Dataset, commit_ids: Iterable[int]
    ) -> Signature:
        return timeseries_backfill_commits_task.signature(
            kwargs=dict(
                commit_ids=commit_ids,
                dataset_names=[dataset.name],
            ),
        )


RegisteredTimeseriesBackfillDatasetTask = celery_app.register_task(
    TimeseriesBackfillDatasetTask()
)
timeseries_backfill_dataset_task = celery_app.tasks[
    RegisteredTimeseriesBackfillDatasetTask.name
]
