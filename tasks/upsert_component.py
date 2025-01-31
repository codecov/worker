import logging

from shared.reports.readonly import ReadOnlyReport
from sqlalchemy.orm import Session

from app import celery_app
from database.models import Commit, MeasurementName
from services.report import ReportService
from services.timeseries import create_measurement_dict, upsert_measurements
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class UpsertComponentTask(BaseCodecovTask):
    def run_impl(
        self,
        db_session: Session,
        commitid: str,
        repoid: int,
        component_id: str,
        flags: list[str],
        paths: list[str],
        *args,
        **kwargs,
    ):
        log.info("Upserting component", extra=dict(commitid=commitid, repoid=repoid))

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )

        current_yaml = get_repo_yaml(commit.repository)

        report_service = ReportService(current_yaml)
        report = report_service.get_existing_report_for_commit(
            commit, report_class=ReadOnlyReport
        )

        if report is None:
            log.warning(
                "Upsert Component: No report found for commit",
                extra=dict(
                    component_id=component_id,
                    commitid=commitid,
                    repoid=repoid,
                ),
            )
            return

        filtered_report = report.filter(flags=flags, paths=paths)
        if filtered_report.totals.coverage is not None:
            measurement = create_measurement_dict(
                MeasurementName.component_coverage.value,
                commit,
                measurable_id=f"{component_id}",
                value=float(filtered_report.totals.coverage),
            )

            upsert_measurements(db_session, [measurement])


registered_task = celery_app.register_task(UpsertComponentTask())
upsert_component_task = celery_app.tasks[registered_task.name]
