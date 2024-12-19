import logging
from typing import Optional

from shared.celery_config import timeseries_delete_task_name
from shared.timeseries.helpers import is_timeseries_enabled
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Repository
from services.timeseries import delete_repository_data, delete_repository_measurements
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class TimeseriesDeleteTask(BaseCodecovTask, name=timeseries_delete_task_name):
    def run_impl(
        self,
        db_session: Session,
        *,
        repository_id: int,
        measurement_only: Optional[bool] = False,
        measurement_type: Optional[str] = None,
        measurement_id: Optional[str] = None,
        **kwargs,
    ):
        if not is_timeseries_enabled():
            log.warning("Timeseries not enabled")
            return {"successful": False, "reason": "Timeseries not enabled"}

        repo = db_session.query(Repository).filter_by(repoid=repository_id).first()
        if not repo:
            log.warning("Repository not found")
            return {"successful": False, "reason": "Repository not found"}

        if measurement_only:
            if measurement_type is None or measurement_id is None:
                log.warning(
                    "Measurement type and ID required to delete measurements only"
                )
                return {
                    "successful": False,
                    "reason": "Measurement type and ID required to delete measurements only",
                }
            delete_repository_measurements(repo, measurement_type, measurement_id)
        else:
            delete_repository_data(repo)

        return {"successful": True}


RegisteredTimeseriesDeleteTask = celery_app.register_task(TimeseriesDeleteTask())
timeseries_delete_task = celery_app.tasks[RegisteredTimeseriesDeleteTask.name]
