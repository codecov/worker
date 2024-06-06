import logging
from typing import Any, Dict

from shared.yaml import UserYaml
from sqlalchemy.orm.session import Session

from app import celery_app
from database.enums import ReportType
from database.models import Commit, Upload
from services.bundle_analysis import BundleAnalysisReportService, ProcessingResult
from services.lock_manager import LockManager, LockRetry, LockType
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

bundle_analysis_save_measurements_task_name = (
    "app.tasks.bundle_analysis.BundleAnalysisMeasurements"
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

        lock_manager = LockManager(
            repoid=repoid,
            commitid=commitid,
            report_type=ReportType.BUNDLE_ANALYSIS,
        )

        try:
            with lock_manager.locked(
                LockType.BUNDLE_ANALYSIS_NOTIFY,
                retry_num=self.request.retries,
            ):
                return self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    uploadid=uploadid,
                    commit_yaml=commit_yaml,
                    previous_result=previous_result,
                )
        except LockRetry as retry:
            self.retry(max_retries=5, countdown=retry.countdown)

    def process_impl_within_lock(
        self,
        db_session: Session,
        repoid: int,
        commitid: str,
        uploadid: int,
        commit_yaml: dict,
        previous_result: Dict[str, Any],
    ):
        log.info(
            "Running bundle analysis save measurements",
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
