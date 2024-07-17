import logging
from typing import Any

from shared.yaml import UserYaml
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Commit, Upload
from services.bundle_analysis.report import (
    BundleAnalysisReportService,
    ProcessingResult,
)
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

bundle_analysis_save_measurements_task_name = (
    "app.tasks.bundle_analysis.BundleAnalysisSaveMeasurements"
)


class BundleAnalysisSaveMeasurementsTask(
    BaseCodecovTask, name=bundle_analysis_save_measurements_task_name
):
    def run_impl(
        self,
        db_session: Session,
        repoid: int,
        commitid: str,
        uploadid: int,
        commit_yaml: dict,
        previous_result: Any,
    ):
        repoid = int(repoid)

        log.info(
            "Starting bundle analysis save measurements",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                previous_result=previous_result,
            ),
        )

        commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        assert commit, "commit not found"

        assert uploadid is not None
        upload = db_session.query(Upload).filter_by(id_=uploadid).first()
        assert upload is not None

        save_measurements = True

        if all((result["error"] is not None for result in previous_result)):
            save_measurements = False

        if save_measurements:
            report_service = BundleAnalysisReportService(
                UserYaml.from_dict(commit_yaml)
            )
            result: ProcessingResult = report_service.save_measurements(commit, upload)
            save_measurements = result.error is None

        log.info(
            "Finished bundle analysis save measurements",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                uploadid=uploadid,
                success=save_measurements,
            ),
        )

        return {"successful": save_measurements}


RegisteredBundleAnalysisSaveMeasurementsTask = celery_app.register_task(
    BundleAnalysisSaveMeasurementsTask()
)
bundle_analysis_save_measurements_task = celery_app.tasks[
    RegisteredBundleAnalysisSaveMeasurementsTask.name
]
