import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

import sentry_sdk
from shared.bundle_analysis import BundleAnalysisReport, BundleAnalysisReportLoader
from shared.bundle_analysis.models import AssetType, MetadataKey
from shared.bundle_analysis.storage import get_bucket_name
from shared.django_apps.bundle_analysis.models import CacheConfig
from shared.django_apps.bundle_analysis.service.bundle_analysis import (
    BundleAnalysisCacheConfigService,
)
from shared.metrics import Counter, inc_counter
from shared.reports.enums import UploadState, UploadType
from shared.storage.exceptions import FileNotInStorageError, PutRequestRateLimitError
from shared.utils.sessions import SessionType
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from database.enums import ReportType
from database.models.core import Commit
from database.models.reports import CommitReport, Upload, UploadError
from database.models.timeseries import Measurement, MeasurementName
from services.archive import ArchiveService
from services.report import BaseReportService
from services.storage import get_storage_client
from services.timeseries import repository_datasets_query

log = logging.getLogger(__name__)


BUNDLE_ANALYSIS_REPORT_PROCESSOR_COUNTER = Counter(
    "bundle_analysis_report_processor_runs",
    "Number of times a BA report processor was run and with what result",
    [
        "result",
        "plugin_name",
        "repository",
    ],
)


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
    previous_bundle_report: Optional[BundleAnalysisReport] = None
    session_id: Optional[int] = None
    bundle_name: Optional[str] = None
    error: Optional[ProcessingError] = None

    def as_dict(self):
        return {
            "upload_id": self.upload.id_,
            "session_id": self.session_id,
            "bundle_name": self.bundle_name,
            "error": self.error.as_dict() if self.error else None,
        }

    def update_upload(self, carriedforward: Optional[bool] = False) -> None:
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

        if carriedforward:
            self.upload.upload_type = SessionType.carriedforward.value
            self.upload_type_id = UploadType.CARRIEDFORWARD.db_id

        BUNDLE_ANALYSIS_REPORT_PROCESSOR_COUNTER.labels(
            result="upload_error" if self.error else "processed",
            plugin_name="n/a",
        ).inc()
        db_session.flush()


class BundleAnalysisReportService(BaseReportService):
    def initialize_and_save_report(
        self, commit: Commit, report_code: str | None = None
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

    def _get_parent_commit(
        self,
        db_session: Session,
        head_commit: Commit,
        head_bundle_report: Optional[BundleAnalysisReport],
    ) -> Optional[Commit]:
        """
        There's two ways to retrieve parent commit of the head commit (in order of priority):
        1. Get the commitSha from head commit bundle report (stored in Metadata during ingestion)
        2. Get the head commit.parent from the DB
        """
        commitid = (
            head_bundle_report
            and head_bundle_report.metadata().get(MetadataKey.COMPARE_SHA)
        ) or head_commit.parent_commit_id

        return (
            db_session.query(Commit)
            .filter_by(
                commitid=commitid,
                repository=head_commit.repository,
            )
            .first()
        )

    @sentry_sdk.trace
    def _previous_bundle_analysis_report(
        self,
        bundle_loader: BundleAnalysisReportLoader,
        commit: Commit,
        head_bundle_report: BundleAnalysisReport | None,
    ) -> BundleAnalysisReport | None:
        """
        Helper function to fetch the parent commit's BAR for the purpose of matching previous bundle's
        Assets to the current one being parsed.
        """
        db_session = commit.get_db_session()

        parent_commit = self._get_parent_commit(
            db_session=db_session,
            head_commit=commit,
            head_bundle_report=head_bundle_report,
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
    def _attempt_init_from_previous_report(
        self,
        commit: Commit,
        bundle_loader: BundleAnalysisReportLoader,
    ) -> BundleAnalysisReport:
        """Attempts to carry over parent bundle analysis report if current commit doesn't have a report.
        Fallback to creating a fresh bundle analysis report if there is no previous report to carry over.
        """
        # load a new copy of the previous bundle report into temp file
        bundle_report = self._previous_bundle_analysis_report(
            bundle_loader, commit, head_bundle_report=None
        )
        if bundle_report:
            # query which bundle names has caching turned on
            bundles_to_be_cached = CacheConfig.objects.filter(
                is_caching=True,
                repo_id=commit.repoid,
            ).values_list("bundle_name", flat=True)

            # For each bundle:
            # if caching is on then update bundle.is_cached property to true
            # if caching is off then delete that bundle from the report
            update_fields = {}
            for bundle in bundle_report.bundle_reports():
                if bundle.name in bundles_to_be_cached:
                    update_fields[bundle.name] = True
                else:
                    bundle_report.delete_bundle_by_name(bundle.name)
            if update_fields:
                bundle_report.update_is_cached(update_fields)
            return bundle_report
        # fallback to create a fresh bundle analysis report if there is no previous report to carry over
        return BundleAnalysisReport()

    @sentry_sdk.trace
    def process_upload(
        self, commit: Commit, upload: Upload, compare_sha: str | None = None
    ) -> ProcessingResult:
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
            bundle_report = self._attempt_init_from_previous_report(
                commit, bundle_loader
            )

        # download raw upload data to local tempfile
        _, local_path = tempfile.mkstemp()
        try:
            session_id, prev_bar, bundle_name = None, None, None
            if upload.storage_path != "":
                with open(local_path, "wb") as f:
                    storage_service.read_file(
                        get_bucket_name(), upload.storage_path, file_obj=f
                    )

                # load the downloaded data into the bundle report
                session_id, bundle_name = bundle_report.ingest(local_path, compare_sha)

                # Retrieve previous commit's BAR and associate past Assets
                prev_bar = self._previous_bundle_analysis_report(
                    bundle_loader, commit, head_bundle_report=bundle_report
                )
                if prev_bar:
                    bundle_report.associate_previous_assets(prev_bar)

                # Turn on caching option by default for all new bundles only for default branch
                if commit.branch == commit.repository.branch:
                    for bundle in bundle_report.bundle_reports():
                        BundleAnalysisCacheConfigService.update_cache_option(
                            commit.repoid, bundle.name
                        )

            # save the bundle report back to storage
            bundle_loader.save(bundle_report, commit_report.external_id)
        except FileNotInStorageError:
            BUNDLE_ANALYSIS_REPORT_PROCESSOR_COUNTER.labels(
                result="file_not_in_storage",
                plugin_name="n/a",
                repository=commit.repository.repoid,
            ).inc()
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
            BUNDLE_ANALYSIS_REPORT_PROCESSOR_COUNTER.labels(
                result="rate_limit_error",
                plugin_name=plugin_name,
            ).inc()
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
            BUNDLE_ANALYSIS_REPORT_PROCESSOR_COUNTER.labels(
                result="parser_error",
                plugin_name=plugin_name,
            ).inc()
            log.error(
                "Unable to parse upload for bundle analysis",
                exc_info=True,
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
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
            previous_bundle_report=prev_bar,
            session_id=session_id,
            bundle_name=bundle_name,
        )

    def _save_to_timeseries(
        self,
        db_session: Session,
        commit: Commit,
        name: str,
        measurable_id: str,
        value: float,
    ):
        command = postgresql.insert(Measurement.__table__).values(
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
    def save_measurements(
        self, commit: Commit, upload: Upload, bundle_name: str
    ) -> ProcessingResult:
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
            bundle_report = bundle_analysis_report.bundle_report(bundle_name)
            if bundle_report:
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
            BUNDLE_ANALYSIS_REPORT_PROCESSOR_COUNTER.labels(
                result="parser_error",
                plugin_name="n/a",
            ).inc()
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
