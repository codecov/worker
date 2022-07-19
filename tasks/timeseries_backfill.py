import logging
from datetime import datetime

from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Repository
from database.models.timeseries import Dataset
from services.timeseries import save_repository_measurements
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
        **kwargs
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
            save_repository_measurements(repository, start_date, end_date)
            db_session.query(Dataset).filter(
                Dataset.repository_id == repository.repoid
            ).update({Dataset.backfilled: True})
            return {"successful": True}
        except ValueError:
            log.error(
                "Invalid date range",
                extra=dict(start_date=start_date, end_date=end_date),
            )
            return {"successful": False}


RegisteredTimeseriesBackfillTask = celery_app.register_task(TimeseriesBackfillTask())
timeseries_backfill_task = celery_app.tasks[RegisteredTimeseriesBackfillTask.name]
