import logging

from shared.celery_config import timeseries_delete_task_name
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Repository
from helpers.timeseries import timeseries_enabled
from services.timeseries import delete_repository_data
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class TimeseriesDeleteTask(BaseCodecovTask):

    name = timeseries_delete_task_name

    async def run_async(
        self,
        db_session: Session,
        *,
        repository_id: int,
        **kwargs,
    ):
        if not timeseries_enabled():
            log.warning("Timeseries not enabled")
            return {"successful": False}

        repo = db_session.query(Repository).filter_by(repoid=repository_id).first()
        if not repo:
            log.warning("Repository not found")
            return {"successful": False}

        delete_repository_data(repo)
        return {"successful": True}


RegisteredTimeseriesDeleteTask = celery_app.register_task(TimeseriesDeleteTask())
timeseries_delete_task = celery_app.tasks[RegisteredTimeseriesDeleteTask.name]
