import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

import sentry_sdk
from shared.bundle_analysis import BundleAnalysisReport, BundleAnalysisReportLoader
from shared.bundle_analysis.storage import get_bucket_name
from shared.reports.enums import UploadState
from shared.storage import get_appropriate_storage_service
from shared.storage.exceptions import FileNotInStorageError

from database.enums import ReportType
from database.models import Commit, CommitReport, Upload, UploadError
from services.archive import ArchiveService
from services.report import BaseReportService
from services.storage import get_storage_client

log = logging.getLogger(__name__)


@dataclass
class ProcessingError:
    code: str
    params: Dict[str, Any]
    is_retryable: bool = False

    def as_dict(self):
        return {"code": self.code, "params": self.params}


@dataclass
class ProcessingResult:
    upload: Upload
    bundle_report: Optional[BundleAnalysisReport] = None
    session_id: Optional[int] = None
    error: Optional[ProcessingError] = None

    def as_dict(self):
        return {
            "upload_id": self.upload.id_,
            "session_id": self.session_id,
            "error": self.error.as_dict() if self.error else None,
        }

    def update_upload(self):
        """
        Updates this result's `Upload` record with information from
        this result.
        """
        db_session = self.upload.get_db_session()

        if self.error:
            self.upload.state = "error"
            self.upload.state_id = UploadState.ERROR.db_id

            upload_error = UploadError(
                upload_id=self.upload.id_,
                error_code=self.error.code,
                error_params=self.error.params,
            )
            db_session.add(upload_error)
        else:
            assert self.bundle_report is not None
            self.upload.state = "processed"
            self.upload.state_id = UploadState.PROCESSED.db_id
            self.upload.order_number = self.session_id

        db_session.flush()


class BundleAnalysisReportService(BaseReportService):
    async def initialize_and_save_report(
        self, commit: Commit, report_code: str = None
    ) -> CommitReport:
        db_session = commit.get_db_session()

        commit_report = (
            db_session.query(CommitReport)
            .filter_by(
                commit_id=commit.id_,
                code=report_code,
                report_type=ReportType.BUNDLE_ANALYSIS.value,
            )
            .first()
        )
        if not commit_report:
            commit_report = CommitReport(
                commit_id=commit.id_,
                code=report_code,
                report_type=ReportType.BUNDLE_ANALYSIS.value,
            )
            db_session.add(commit_report)
            db_session.flush()
        return commit_report

    @sentry_sdk.trace
    def process_upload(self, upload: Upload) -> ProcessingResult:
        """
        Download and parse the data associated with the given upload and
        merge the results into a bundle report.
        """
        commit_report: CommitReport = upload.report
        repo_hash = ArchiveService.get_archive_hash(commit_report.commit.repository)
        storage_service = get_storage_client()
        bundle_loader = BundleAnalysisReportLoader(storage_service, repo_hash)

        # fetch existing bundle report from storage
        bundle_report = bundle_loader.load(commit_report.external_id)

        if bundle_report is None:
            bundle_report = BundleAnalysisReport()

        # download raw upload data to local tempfile
        _, local_path = tempfile.mkstemp()
        try:
            with open(local_path, "wb") as f:
                storage_service.read_file(
                    get_bucket_name(), upload.storage_path, file_obj=f
                )

            # load the downloaded data into the bundle report
            session_id = bundle_report.ingest(local_path)

            # save the bundle report back to storage
            bundle_loader.save(bundle_report, commit_report.external_id)
        except FileNotInStorageError:
            return ProcessingResult(
                upload=upload,
                error=ProcessingError(
                    code="file_not_in_storage",
                    params={"location": upload.storage_path},
                    is_retryable=True,
                ),
            )
        finally:
            os.remove(local_path)

        return ProcessingResult(
            upload=upload,
            bundle_report=bundle_report,
            session_id=session_id,
        )
