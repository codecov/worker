import logging
import os
import tempfile
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

import sentry_sdk
from sentry_sdk import metrics as sentry_metrics
from shared.bundle_analysis import (
    BundleAnalysisComparison,
    BundleAnalysisReport,
    BundleAnalysisReportLoader,
    BundleChange,
)
from shared.bundle_analysis.models import AssetType
from shared.bundle_analysis.storage import get_bucket_name
from shared.reports.enums import UploadState
from shared.storage import get_appropriate_storage_service
from shared.storage.exceptions import FileNotInStorageError, PutRequestRateLimitError
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import TorngitClientError
from shared.yaml import UserYaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.enums import ReportType
from database.models import (
    Commit,
    CommitReport,
    Measurement,
    MeasurementName,
    Repository,
    Upload,
    UploadError,
)
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from services.archive import ArchiveService
from services.report import BaseReportService
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.storage import get_storage_client
from services.timeseries import repository_datasets_query
from services.urls import get_bundle_analysis_pull_url
from services.yaml import read_yaml_field

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
    commit: Commit
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
            self.commit.state = "error"
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
            self.commit.state = "complete"
            self.upload.state = "processed"
            self.upload.state_id = UploadState.PROCESSED.db_id
            self.upload.order_number = self.session_id

        sentry_metrics.incr(
            "bundle_analysis_upload",
            tags={
                "result": "upload_error" if self.error else "processed",
            },
        )

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

    def _previous_bundle_analysis_report(
        self, bundle_loader: BundleAnalysisReportLoader, commit: Commit
    ) -> Optional[BundleAnalysisReport]:
        """
        Helper function to fetch the parent commit's BAR for the purpose of matching previous bundle's
        Assets to the current one being parsed.
        """
        if commit.parent_commit_id is None:
            return None

        db_session = commit.get_db_session()
        parent_commit = (
            db_session.query(Commit)
            .filter_by(
                commitid=commit.parent_commit_id,
                repository=commit.repository,
            )
            .first()
        )
        if parent_commit is None:
            return None

        parent_commit_report = (
            db_session.query(CommitReport)
            .filter_by(
                commit_id=parent_commit.id_,
                report_type=ReportType.BUNDLE_ANALYSIS.value,
            )
            .first()
        )
        if parent_commit_report is None:
            return None

        return bundle_loader.load(parent_commit_report.external_id)

    @sentry_sdk.trace
    def process_upload(self, commit: Commit, upload: Upload) -> ProcessingResult:
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

            # Retrieve previous commit's BAR and associate past Assets
            prev_bar = self._previous_bundle_analysis_report(bundle_loader, commit)
            if prev_bar:
                bundle_report.associate_previous_assets(prev_bar)

            # save the bundle report back to storage
            bundle_loader.save(bundle_report, commit_report.external_id)
        except FileNotInStorageError:
            return ProcessingResult(
                upload=upload,
                commit=commit,
                error=ProcessingError(
                    code="file_not_in_storage",
                    params={"location": upload.storage_path},
                    is_retryable=True,
                ),
            )
        except PutRequestRateLimitError as e:
            plugin_name = getattr(e, "bundle_analysis_plugin_name", "unknown")
            sentry_metrics.incr(
                "bundle_analysis_upload",
                tags={
                    "result": "rate_limit_error",
                    "plugin_name": plugin_name,
                },
            )
            return ProcessingResult(
                upload=upload,
                commit=commit,
                error=ProcessingError(
                    code="rate_limit_error",
                    params={"location": upload.storage_path},
                    is_retryable=True,
                ),
            )
        except Exception as e:
            # Metrics to count number of parsing errors of bundle files by plugins
            plugin_name = getattr(e, "bundle_analysis_plugin_name", "unknown")
            sentry_metrics.incr(
                "bundle_analysis_upload",
                tags={
                    "result": "parser_error",
                    "plugin_name": plugin_name,
                },
            )
            return ProcessingResult(
                upload=upload,
                commit=commit,
                error=ProcessingError(
                    code="parser_error",
                    params={
                        "location": upload.storage_path,
                        "plugin_name": plugin_name,
                    },
                    is_retryable=False,
                ),
            )
        finally:
            os.remove(local_path)

        return ProcessingResult(
            upload=upload,
            commit=commit,
            bundle_report=bundle_report,
            session_id=session_id,
        )

    def _save_to_timeseries(
        self,
        db_session: Session,
        commit: Commit,
        name: str,
        measurable_id: str,
        value: float,
    ):
        command = insert(Measurement.__table__).values(
            name=name,
            owner_id=commit.repository.ownerid,
            repo_id=commit.repoid,
            measurable_id=measurable_id,
            branch=commit.branch,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            value=value,
        )
        command = command.on_conflict_do_update(
            index_elements=[
                Measurement.name,
                Measurement.owner_id,
                Measurement.repo_id,
                Measurement.measurable_id,
                Measurement.commit_sha,
                Measurement.timestamp,
            ],
            set_=dict(
                branch=command.excluded.branch,
                value=command.excluded.value,
            ),
        )
        db_session.execute(command)
        db_session.flush()

    @sentry_sdk.trace
    def save_measurements(self, commit: Commit, upload: Upload) -> ProcessingResult:
        """
        Save timeseries measurements for this bundle analysis report
        """
        try:
            commit_report: CommitReport = upload.report
            repo_hash = ArchiveService.get_archive_hash(commit_report.commit.repository)
            storage_service = get_storage_client()
            bundle_loader = BundleAnalysisReportLoader(storage_service, repo_hash)

            # fetch existing bundle report from storage
            bundle_analysis_report = bundle_loader.load(commit_report.external_id)

            dataset_names = [
                dataset.name for dataset in repository_datasets_query(commit.repository)
            ]

            db_session = commit.get_db_session()
            for bundle_report in bundle_analysis_report.bundle_reports():
                # For overall bundle size
                if MeasurementName.bundle_analysis_report_size.value in dataset_names:
                    self._save_to_timeseries(
                        db_session,
                        commit,
                        MeasurementName.bundle_analysis_report_size.value,
                        bundle_report.name,
                        bundle_report.total_size(),
                    )

                # For individual javascript associated assets using UUID
                if MeasurementName.bundle_analysis_asset_size.value in dataset_names:
                    for asset in bundle_report.asset_reports():
                        if asset.asset_type == AssetType.JAVASCRIPT:
                            self._save_to_timeseries(
                                db_session,
                                commit,
                                MeasurementName.bundle_analysis_asset_size.value,
                                asset.uuid,
                                asset.size,
                            )

                # For asset types sizes
                asset_type_map = {
                    MeasurementName.bundle_analysis_font_size: AssetType.FONT,
                    MeasurementName.bundle_analysis_image_size: AssetType.IMAGE,
                    MeasurementName.bundle_analysis_stylesheet_size: AssetType.STYLESHEET,
                    MeasurementName.bundle_analysis_javascript_size: AssetType.JAVASCRIPT,
                }
                for measurement_name, asset_type in asset_type_map.items():
                    if measurement_name.value in dataset_names:
                        total_size = 0
                        for asset in bundle_report.asset_reports():
                            if asset.asset_type == asset_type:
                                total_size += asset.size
                        self._save_to_timeseries(
                            db_session,
                            commit,
                            measurement_name.value,
                            bundle_report.name,
                            total_size,
                        )

            return ProcessingResult(
                upload=upload,
                commit=commit,
            )
        except Exception:
            sentry_metrics.incr(
                "bundle_analysis_upload",
                tags={
                    "result": "parser_error",
                    "repository": commit.repository.repoid,
                },
            )
            return ProcessingResult(
                upload=upload,
                commit=commit,
                error=ProcessingError(
                    code="measurement_save_error",
                    params={
                        "location": upload.storage_path,
                        "repository": commit.repository.repoid,
                    },
                    is_retryable=False,
                ),
            )


class ComparisonError(Exception):
    pass


class MissingBaseCommit(ComparisonError):
    pass


class MissingBaseReport(ComparisonError):
    pass


class MissingHeadCommit(ComparisonError):
    pass


class MissingHeadReport(ComparisonError):
    pass


class ComparisonLoader:
    def __init__(self, pull: EnrichedPull):
        self.pull = pull

    @cached_property
    def repository(self) -> Repository:
        return self.pull.database_pull.repository

    @cached_property
    def base_commit(self) -> Commit:
        commit = self.pull.database_pull.get_comparedto_commit()
        if commit is None:
            raise MissingBaseCommit()
        return commit

    @cached_property
    def head_commit(self) -> Commit:
        commit = self.pull.database_pull.get_head_commit()
        if commit is None:
            raise MissingHeadCommit()
        return commit

    @cached_property
    def base_commit_report(self) -> CommitReport:
        commit_report = self.base_commit.commit_report(
            report_type=ReportType.BUNDLE_ANALYSIS
        )
        if commit_report is None:
            raise MissingBaseReport()
        return commit_report

    @cached_property
    def head_commit_report(self) -> CommitReport:
        commit_report = self.head_commit.commit_report(
            report_type=ReportType.BUNDLE_ANALYSIS
        )
        if commit_report is None:
            raise MissingHeadReport()
        return commit_report

    def get_comparison(self) -> BundleAnalysisComparison:
        loader = BundleAnalysisReportLoader(
            storage_service=get_appropriate_storage_service(),
            repo_key=ArchiveService.get_archive_hash(self.repository),
        )

        return BundleAnalysisComparison(
            loader=loader,
            base_report_key=self.base_commit_report.external_id,
            head_report_key=self.head_commit_report.external_id,
        )


@dataclass
class BundleRows:
    bundle_name: str
    size: str
    change: str


class Notifier:
    def __init__(
        self,
        commit: Commit,
        current_yaml: UserYaml,
        gh_app_installation_name: str | None = None,
    ):
        self.commit = commit
        self.current_yaml = current_yaml
        self.gh_app_installation_name = (
            gh_app_installation_name or GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )

    @cached_property
    def repository(self) -> Repository:
        return self.commit.repository

    @cached_property
    def commit_report(self) -> Optional[CommitReport]:
        return self.commit.commit_report(report_type=ReportType.BUNDLE_ANALYSIS)

    @cached_property
    def repository_service(self) -> TorngitBaseAdapter:
        return get_repo_provider_service(
            self.commit.repository,
            installation_name_to_use=self.gh_app_installation_name,
        )

    @cached_property
    def bundle_analysis_loader(self):
        repo_hash = ArchiveService.get_archive_hash(self.repository)
        storage_service = get_storage_client()
        return BundleAnalysisReportLoader(storage_service, repo_hash)

    @cached_property
    def bundle_report(self) -> Optional[BundleAnalysisReport]:
        return self.bundle_analysis_loader.load(self.commit_report.external_id)

    def _has_required_changes(
        self, comparison: BundleAnalysisComparison, pull: EnrichedPull
    ) -> bool:
        """Verifies if the notifier should notify according to the configured required_changes.
        Changes are defined by the user in UserYaml. Default is "always notify".
        Required changes are bypassed if a comment already exists, because we should update the comment.
        """
        if pull.database_pull.bundle_analysis_commentid:
            log.info(
                "Skipping required_changes verification because comment already exists",
                extra=dict(pullid=pull.database_pull.id, commitid=self.commit.commitid),
            )
            return True

        required_changes: bool | Literal["bundle_increase"] = read_yaml_field(
            self.current_yaml, ("comment", "require_bundle_changes"), False
        )
        changes_threshold: int = read_yaml_field(
            self.current_yaml, ("comment", "bundle_change_threshold"), 0
        )
        match required_changes:
            case False:
                return True
            case True:
                return abs(comparison.total_size_delta) > changes_threshold
            case "bundle_increase":
                return (
                    comparison.total_size_delta > 0
                    and comparison.total_size_delta > changes_threshold
                )
            case _:
                log.warning(
                    "Unknown value for required_changes",
                    extra=dict(
                        pull=pull.database_pull.id, commitid=self.commit.commitid
                    ),
                )
                return True

    async def notify(self) -> bool:
        if self.commit_report is None:
            log.warning(
                "Missing commit report", extra=dict(commitid=self.commit.commitid)
            )
            return False

        if self.bundle_report is None:
            log.warning(
                "Missing bundle report",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=self.commit_report.external_id,
                ),
            )
            return False

        pull: Optional[
            EnrichedPull
        ] = await fetch_and_update_pull_request_information_from_commit(
            self.repository_service, self.commit, self.current_yaml
        )
        if pull is None:
            log.warning(
                "No pull for commit",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=self.commit_report.external_id,
                ),
            )
            return False

        pullid = pull.database_pull.pullid
        bundle_comparison = ComparisonLoader(pull).get_comparison()

        if not self._has_required_changes(bundle_comparison, pull):
            # Skips the comment and returns successful notification
            log.info(
                "Not enough changes to notify bundle PR comment",
                extra=dict(
                    commitid=self.commit.commitid,
                    pullid=pullid,
                ),
            )
            return True

        message = self._build_message(pull=pull, comparison=bundle_comparison)
        try:
            comment_id = pull.database_pull.bundle_analysis_commentid
            if comment_id:
                await self.repository_service.edit_comment(pullid, comment_id, message)
            else:
                res = await self.repository_service.post_comment(pullid, message)
                pull.database_pull.bundle_analysis_commentid = res["id"]
            return True
        except TorngitClientError:
            log.error(
                "Error creating/updating PR comment",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=self.commit_report.external_id,
                    pullid=pullid,
                ),
            )
            return False

    def _build_message(
        self, pull: EnrichedPull, comparison: BundleAnalysisComparison
    ) -> str:
        bundle_changes = comparison.bundle_changes()

        bundle_rows = self._create_bundle_rows(
            bundle_changes=bundle_changes, comparison=comparison
        )
        return self._write_lines(
            bundle_rows=bundle_rows,
            total_size_delta=comparison.total_size_delta,
            pull=pull,
        )

    def _create_bundle_rows(
        self,
        bundle_changes: Iterator[BundleChange],
        comparison: BundleAnalysisComparison,
    ) -> Tuple[List[BundleRows], int]:
        bundle_rows = []

        # Calculate bundle change data in one loop since bundle_changes is a generator
        for bundle_change in bundle_changes:
            # Define row table data
            bundle_name = bundle_change.bundle_name
            if bundle_change.change_type == BundleChange.ChangeType.REMOVED:
                size = "(removed)"
            else:
                head_bundle_report = comparison.head_report.bundle_report(bundle_name)
                size = self._bytes_readable(head_bundle_report.total_size())

            change_size = bundle_change.size_delta
            icon = ""
            if change_size > 0:
                icon = ":arrow_up:"
            elif change_size < 0:
                icon = ":arrow_down:"

            bundle_rows.append(
                BundleRows(
                    bundle_name=bundle_name,
                    size=size,
                    change=f"{self._bytes_readable(change_size)} {icon}",
                )
            )

        return bundle_rows

    def _write_lines(
        self, bundle_rows: List[BundleRows], total_size_delta: int, pull: EnrichedPull
    ) -> str:
        # Write lines
        pull_url = get_bundle_analysis_pull_url(pull=pull.database_pull)

        lines = [
            f"## [Bundle]({pull_url}) Report",
            "",
        ]

        if total_size_delta == 0:
            lines.append("Bundle size has no change :white_check_mark:")
            return "\n".join(lines)

        bundles_total_size = self._bytes_readable(total_size_delta)
        if total_size_delta > 0:
            lines.append(
                f"Changes will increase total bundle size by {bundles_total_size} :arrow_up:"
            )
        else:
            lines.append(
                f"Changes will decrease total bundle size by {bundles_total_size} :arrow_down:"
            )
        lines.append("")

        # table of bundles
        lines += [
            "| Bundle name | Size | Change |",
            "| ----------- | ---- | ------ |",
        ]
        for bundle_row in bundle_rows:
            lines.append(
                f"| {bundle_row.bundle_name} | {bundle_row.size} | {bundle_row.change} |"
            )

        return "\n".join(lines)

    def _bytes_readable(self, bytes: int) -> str:
        # TODO: this could maybe be a helper method in `shared`

        bytes = abs(bytes)

        if bytes < 1000:
            bytes = round(bytes, 2)
            return f"{bytes} bytes"

        kilobytes = bytes / 1000
        if kilobytes < 1000:
            kilobytes = round(kilobytes, 2)
            return f"{kilobytes}kB"

        megabytes = kilobytes / 1000
        if megabytes < 1000:
            megabytes = round(megabytes, 2)
            return f"{megabytes}MB"

        gigabytes = round(megabytes / 1000, 2)
        return f"{gigabytes}GB"
