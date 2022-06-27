import logging

import dateutil.parser as dateparser
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Repository
from services.timeseries import save_repository_measurements
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class TimeseriesBackfillTask(BaseCodecovTask):

    # FIXME: add name to `shared.celery_config`
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
            start_date = dateparser.parse(start_date)
            end_date = dateparser.parse(end_date)
            save_repository_measurements(repository, start_date, end_date)
            return {"successful": True}
        except dateparser.ParserError:
            log.error(
                "Invalid date range",
                extra=dict(start_date=start_date, end_date=end_date),
            )
            return {"successful": False}


RegisteredTimeseriesBackfillTask = celery_app.register_task(TimeseriesBackfillTask())
timeseries_backfill_task = celery_app.tasks[RegisteredTimeseriesBackfillTask.name]
