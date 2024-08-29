import logging
from copy import deepcopy
from typing import Any, Dict

from asgiref.sync import async_to_sync
from celery.exceptions import CeleryError, SoftTimeLimitExceeded
from shared.reports.enums import UploadState
from shared.yaml import UserYaml
from sqlalchemy.exc import SQLAlchemyError

from app import celery_app
from database.enums import ReportType
from database.models import Commit, Upload
from services.bundle_analysis.report import (
    BundleAnalysisReportService,
    ProcessingResult,
)
from services.lock_manager import LockManager, LockRetry, LockType
from tasks.base import BaseCodecovTask
from tasks.bundle_analysis_save_measurements import (
    bundle_analysis_save_measurements_task_name,
)

log = logging.getLogger(__name__)

bundle_analysis_processor_task_name = (
    "app.tasks.bundle_analysis.BundleAnalysisProcessor"
)


class BundleAnalysisProcessorTask(
    BaseCodecovTask, name=bundle_analysis_processor_task_name
):
    def run_impl(
        self,
        db_session,
        # Celery `chain` injects this argument - it's the returned result
        # from the prior task in the chain
        previous_result: Dict[str, Any],
        *,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        params: Dict[str, Any],
        **kwargs,
    ):
        repoid = int(repoid)
        commit_yaml = UserYaml.from_dict(commit_yaml)

        log.info(
            "Starting bundle analysis processor",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                params=params,
            ),
        )

        lock_manager = LockManager(
            repoid=repoid,
            commitid=commitid,
            report_type=ReportType.BUNDLE_ANALYSIS,
        )

        try:
            with lock_manager.locked(
                LockType.BUNDLE_ANALYSIS_PROCESSING,
                retry_num=self.request.retries,
            ):
                return self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    params=deepcopy(params),
                    previous_result=previous_result,
                    **kwargs,
                )
        except LockRetry as retry:
            self.retry(max_retries=5, countdown=retry.countdown)

    def process_impl_within_lock(
        self,
        *,
        db_session,
        repoid: int,
        commitid: str,
        commit_yaml: UserYaml,
        params: Dict[str, Any],
        previous_result: Dict[str, Any],
        **kwargs,
    ):
        log.info(
            "Running bundle analysis processor",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                params=params,
                parent_task=self.request.parent_id,
            ),
        )

        commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        assert commit, "commit not found"

        report_service = BundleAnalysisReportService(commit_yaml)

        # these are the task results from prior processor tasks in the chain
        # (they get accumulated as we execute each task in succession)
        processing_results = previous_result.get("results", [])

        # these are populated in the upload task
        # unless when this task is called on a non-BA upload then we have to create an empty upload
        upload_pk, carriedforward = params["upload_pk"], False
        if upload_pk is None:
            commit_report = async_to_sync(report_service.initialize_and_save_report)(
                commit
            )
            upload_pk = report_service.create_report_upload(
                {"url": ""}, commit_report
            ).id_
            carriedforward = True

        upload = db_session.query(Upload).filter_by(id_=upload_pk).first()
        assert upload is not None

        # Override base commit of comparisons with a custom commit SHA if applicable
        compare_sha = params.get("bundle_analysis_compare_sha")

        try:
            log.info(
                "Processing bundle analysis upload",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    commit_yaml=commit_yaml,
                    params=params,
                    upload_id=upload.id_,
                    parent_task=self.request.parent_id,
                    compare_sha=compare_sha,
                ),
            )
            assert params.get("commit") == commit.commitid

            result: ProcessingResult = report_service.process_upload(
                commit, upload, compare_sha
            )
            if result.error and result.error.is_retryable and self.request.retries == 0:
                # retryable error and no retry has already be scheduled
                self.retry(max_retries=5, countdown=20)
            result.update_upload(carriedforward=carriedforward)

            processing_results.append(result.as_dict())
        except (CeleryError, SoftTimeLimitExceeded, SQLAlchemyError):
            raise
        except Exception:
            log.exception(
                "Unable to process bundle analysis upload",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    commit_yaml=commit_yaml,
                    params=params,
                    upload_id=upload.id_,
                    parent_task=self.request.parent_id,
                ),
            )
            upload.state_id = UploadState.ERROR.db_id
            upload.state = "error"
            raise
        finally:
            if result.bundle_report:
                result.bundle_report.cleanup()
            if result.previous_bundle_report:
                result.previous_bundle_report.cleanup()

        # Create task to save bundle measurements
        self.app.tasks[bundle_analysis_save_measurements_task_name].apply_async(
            kwargs=dict(
                commitid=commit.commitid,
                repoid=commit.repoid,
                uploadid=upload.id_,
                commit_yaml=commit_yaml.to_dict(),
                previous_result=processing_results,
            )
        )

        log.info(
            "Finished bundle analysis processor",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                params=params,
                results=processing_results,
                parent_task=self.request.parent_id,
            ),
        )

        return {"results": processing_results}


RegisteredBundleAnalysisProcessorTask = celery_app.register_task(
    BundleAnalysisProcessorTask()
)
bundle_analysis_processor_task = celery_app.tasks[
    RegisteredBundleAnalysisProcessorTask.name
]
