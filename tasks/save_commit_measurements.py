import logging
from typing import Iterable

from shared.celery_config import timeseries_save_commit_measurements_task_name
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.core import Commit
from services.timeseries import save_commit_measurements
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class SaveCommitMeasurementsTask(
    BaseCodecovTask, name=timeseries_save_commit_measurements_task_name
):
    async def run_async(
        self,
        db_session: Session,
        commitid: str,
        repoid: int,
        dataset_names: Iterable[int] = None,
        *args,
        **kwargs
    ):
        log.info(
            "Received save_commit_measurements task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                dataset_names=dataset_names,
                parent_task=self.request.parent_id,
            ),
        )

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )

        if commit is None:
            return {"successful": False, "error": "no_commit_in_db"}

        try:
            # TODO: We should improve on the error handling/logs inside this fn
            print("asdfasdf")
            save_commit_measurements(commit=commit, dataset_names=dataset_names)
            print("asdfasdf123")
            return {"successful": True}
        except Exception:
            log.exception(
                "An error happened while saving commit measurements",
                extra=dict(commitid=commitid, task_args=args, task_kwargs=kwargs),
            )
            return {"successful": False, "error": "exception"}


RegisteredSaveCommitMeasurementsTask = celery_app.register_task(
    SaveCommitMeasurementsTask()
)
save_commit_measurements_task = celery_app.tasks[
    RegisteredSaveCommitMeasurementsTask.name
]
