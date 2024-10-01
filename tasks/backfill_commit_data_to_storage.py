import logging
from enum import Enum
from typing import List, Optional, TypedDict

from shared.utils.enums import TaskConfigGroup
from sqlalchemy.orm.session import Session

from app import celery_app
from database.enums import ReportType
from database.models.core import Commit
from database.models.reports import CommitReport, ReportDetails
from services.report import ReportService
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class BackfillError(Enum):
    commit_not_found = "commit_not_found"
    missing_data = "missing_data"


class BackfillResult(TypedDict):
    success: bool
    errors: List[BackfillError]


class BackfillCommitDataToStorageTask(
    BaseCodecovTask,
    name=f"app.tasks.{TaskConfigGroup.archive.value}.BackfillCommitDataToStorage",
):
    def run_impl(
        self,
        db_session: Session,
        *,
        commitid: int,
        **kwargs,
    ) -> BackfillResult:
        commit: Optional[Commit] = db_session.query(Commit).get(commitid)
        if commit is None:
            log.error("Commit not found.", extra=dict(commitid=commitid))
            return {"success": False, "errors": [BackfillError.commit_not_found.value]}
        # Handle the report_json to storage
        report_json_backfill_result = self.handle_report_json(db_session, commit)
        # Handle report related classes
        report_classes_backfill_result = self.handle_all_report_rows(db_session, commit)
        # We can leave to BaseCodeovTask to commit the changes to DB
        return {
            "success": report_json_backfill_result["success"]
            and report_classes_backfill_result["success"],
            "errors": report_classes_backfill_result.get("errors")
            + report_json_backfill_result.get("errors"),
        }

    def handle_report_json(self, dbsession: Session, commit: Commit) -> BackfillResult:
        if commit._report_json_storage_path is not None:
            if commit._report_json is not None:
                log.warning(
                    "Both _report_json AND _report_json_storage_path are set. Leaving as is.",
                    extra=dict(commitid=commit.id, commit=commit.commitid),
                )
            log.debug(
                "Commit info already in storage",
                extra=dict(commitid=commit.id, commit=commit.commitid),
            )
            return {"success": True, "errors": []}
        if commit._report_json is not None:
            # write to storage and clears out db field
            commit.report_json = commit._report_json
            return {"success": True, "errors": []}
        log.warning(
            "Neither _report_json nor _report_json_storage_path are set. Nothing to do.",
            extra=dict(commitid=commit.id, commit=commit.commitid),
        )
        return {"success": False, "errors": [BackfillError.missing_data.value]}

    def handle_all_report_rows(
        self, db_session: Session, commit: Commit
    ) -> BackfillResult:
        report_rows = (
            db_session.query(CommitReport)
            .filter_by(commit_id=commit.id_)
            .filter(
                (CommitReport.report_type == None)  # noqa: E711
                | (CommitReport.report_type == ReportType.COVERAGE.value)
            )
            .all()
        )
        if report_rows == []:
            new_report_row = CommitReport(
                commit_id=commit.id_,
                code=None,
                report_type=ReportType.COVERAGE.value,
            )
            db_session.add(new_report_row)
            db_session.flush()
            report_rows = [new_report_row]
        aggregate_results = dict(success=True, errors=[])
        for row in report_rows:
            result = self.handle_single_report_row(db_session, commit, row)
            aggregate_results["success"] = (
                aggregate_results["success"] and result["success"]
            )
            aggregate_results["errors"].extend(result["errors"])
        return aggregate_results

    def handle_single_report_row(
        self, db_session: Session, commit: Commit, report_row: CommitReport
    ) -> BackfillResult:
        report_details = (
            db_session.query(ReportDetails).filter_by(report_id=report_row.id_).first()
        )
        if report_details is None:
            report_details = ReportDetails(
                report_id=report_row.id_,
                _files_array=[],
                report=report_row,
            )
            db_session.add(report_details)
            db_session.flush()

            repo_yaml = get_repo_yaml(commit.repository)
            report_service = ReportService(current_yaml=repo_yaml)
            actual_report = report_service.get_existing_report_for_commit(
                commit, report_code=None
            )
            if actual_report is not None:
                report_service.save_report(commit, actual_report)
        if report_details._files_array_storage_path is not None:
            if report_details._files_array is not None:
                log.warning(
                    "Both _files_array_storage_path AND _files_array are set. Leaving as is.",
                    extra=dict(
                        commitid=commit.id,
                        commit=commit.commitid,
                        commit_report=report_row.id_,
                        report_details=report_details.id_,
                    ),
                )
            return {"success": True, "errors": []}
        if report_details._files_array is not None:
            # write to storage and clears out db field
            report_details.files_array = report_details._files_array
            return {"success": True, "errors": []}
        log.warning(
            "Neither _files_array_storage_path nor _files_array are set. Nothing to do.",
            extra=dict(
                commitid=commit.id,
                commit=commit.commitid,
                commit_report=report_row.id_,
                report_details=report_details.id_,
            ),
        )
        return {"success": False, "errors": [BackfillError.missing_data.value]}


RegisteredBackfillCommitDataToStorageTask = celery_app.register_task(
    BackfillCommitDataToStorageTask()
)
backfill_commit_data_to_storage_task = celery_app.tasks[
    RegisteredBackfillCommitDataToStorageTask.name
]
