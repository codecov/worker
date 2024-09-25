import copy
import itertools
import logging
import sys
import uuid
from dataclasses import dataclass
from json import loads
from time import time
from typing import Any, Mapping, Optional, Sequence

import sentry_sdk
from asgiref.sync import async_to_sync
from celery.exceptions import SoftTimeLimitExceeded
from shared.config import get_config
from shared.django_apps.reports.models import ReportType
from shared.metrics import metrics
from shared.reports.carryforward import generate_carryforward_report
from shared.reports.editable import EditableReport
from shared.reports.enums import UploadState, UploadType
from shared.reports.resources import Report
from shared.reports.types import ReportFileSummary, ReportTotals
from shared.storage.exceptions import FileNotInStorageError
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import TorngitError
from shared.upload.constants import UploadErrorCode
from shared.upload.utils import UploaderType, insert_coverage_measurement
from shared.utils.sessions import Session, SessionType
from shared.yaml import UserYaml

from database.models import Commit, Repository, Upload, UploadError
from database.models.reports import (
    AbstractTotals,
    CommitReport,
    ReportDetails,
    ReportLevelTotals,
    RepositoryFlag,
    UploadLevelTotals,
)
from helpers.environment import Environment, get_current_env
from helpers.exceptions import (
    OwnerWithoutValidBotError,
    ReportEmptyError,
    ReportExpiredException,
    RepositoryWithoutValidBotError,
)
from helpers.labels import get_labels_per_session
from helpers.telemetry import MetricContext
from rollouts import (
    CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER,
    PARALLEL_UPLOAD_PROCESSING_BY_REPO,
)
from services.archive import ArchiveService
from services.report.parser import get_proper_parser
from services.report.parser.types import ParsedRawReport
from services.report.parser.version_one import VersionOneReportParser
from services.report.prometheus_metrics import (
    RAW_UPLOAD_RAW_REPORT_COUNT,
    RAW_UPLOAD_SIZE,
)
from services.report.raw_upload_processor import process_raw_upload
from services.repository import get_repo_provider_service
from services.yaml.reader import get_paths_from_flags, read_yaml_field


@dataclass
class ProcessingError:
    code: UploadErrorCode
    params: dict[str, Any]
    is_retryable: bool = False

    def as_dict(self):
        return {"code": self.code, "params": self.params}


@dataclass
class ProcessingResult:
    session: Session
    report: Report | None = None
    error: ProcessingError | None = None


@dataclass
class RawReportInfo:
    raw_report: ParsedRawReport | None = None
    archive_url: str = ""
    upload: str = ""
    error: ProcessingError | None = None


log = logging.getLogger(__name__)


class NotReadyToBuildReportYetError(Exception):
    pass


class BaseReportService:
    """
    This is the class that will handle anything report-handling related

    Attributes:
        current_yaml (Mapping[str, Any]): The configuration we need to follow.
            It's always the user yaml, but might have different uses on different places
    """

    def __init__(self, current_yaml: UserYaml):
        if isinstance(current_yaml, dict):
            current_yaml = UserYaml(current_yaml)
        self.current_yaml = current_yaml

    def initialize_and_save_report(
        self, commit: Commit, report_code: str | None = None
    ) -> CommitReport:
        raise NotImplementedError()

    def fetch_report_upload(
        self, commit_report: CommitReport, upload_id: int
    ) -> Upload:
        """
        Fetch Upload by the given upload_id.
        :raises: Exception if Upload is not found.
        """
        db_session = commit_report.get_db_session()
        upload = db_session.query(Upload).filter_by(id_=int(upload_id)).first()
        if not upload:
            raise Exception(
                f"Failed to find existing upload by ID ({upload_id})",
                dict(
                    commit=commit_report.commit_id,
                    repo=commit_report.commit.repoid,
                    upload_id=upload_id,
                ),
            )
        return upload

    def create_report_upload(
        self, normalized_arguments: Mapping[str, str], commit_report: CommitReport
    ) -> Upload:
        """
        Creates an `Upload` from the user-given arguments to a job

        The end goal here is that the `Upload` should have all the information needed to
            hypothetically redo the job later

        Args:
            normalized_arguments (Mapping[str, str]): The arguments as given by the user
            commit_report (CommitReport): The commit_report we will attach this `Uplaod` to

        Returns:
            Upload
        """
        db_session = commit_report.get_db_session()
        name = normalized_arguments.get("name")
        upload = Upload(
            external_id=normalized_arguments.get("reportid"),
            build_code=normalized_arguments.get("build"),
            build_url=normalized_arguments.get("build_url"),
            env=None,
            report_id=commit_report.id_,
            job_code=normalized_arguments.get("job"),
            name=(name[:100] if name else None),
            provider=normalized_arguments.get("service"),
            state="started",
            storage_path=normalized_arguments.get("url"),
            order_number=None,
            upload_extras={},
            upload_type=SessionType.uploaded.value,
            state_id=UploadState.UPLOADED.db_id,
            upload_type_id=UploadType.UPLOADED.db_id,
        )
        db_session.add(upload)
        db_session.flush()
        return upload


class ReportService(BaseReportService):
    metrics_prefix = "services.report"

    def __init__(
        self, current_yaml: UserYaml, gh_app_installation_name: str | None = None
    ):
        super().__init__(current_yaml)
        self.flag_dict = None
        self.gh_app_installation_name = gh_app_installation_name

    def has_initialized_report(self, commit: Commit) -> bool:
        """Says whether a commit has already initialized its report or not

        Args:
            commit (Commit): The commit we want to know about

        Returns:
            bool: Whether the commit already has initialized a report
        """
        return (
            commit._report_json is not None
            or commit._report_json_storage_path is not None
        )

    @sentry_sdk.trace
    def initialize_and_save_report(
        self, commit: Commit, report_code: str = None
    ) -> CommitReport:
        """
            Initializes the commit report


            This is one of the main entrypoint of this class. It takes care of:
                - Creating the most basic models relating to that commit
                    report (CommitReport and ReportDetails), if needed
                - If that commit is old-style (was created before the report models were installed),
                    it takes care of backfilling all the information from the report into the new
                    report models
                - If that commit needs something to be carryforwarded, it does that logic and
                    already saves the report into the database and storage

        Args:
            commit (Commit): The commit we want to initialize

        Returns:
            CommitReport: The CommitReport for that commit
        """
        db_session = commit.get_db_session()
        current_report_row = (
            db_session.query(CommitReport)
            .filter_by(commit_id=commit.id_, code=report_code)
            .filter(
                (CommitReport.report_type == None)  # noqa: E711
                | (CommitReport.report_type == ReportType.COVERAGE.value)
            )
            .first()
        )
        if not current_report_row:
            # This happens if the commit report is being created for the first time
            # or backfilled
            current_report_row = CommitReport(
                commit_id=commit.id_,
                code=report_code,
                report_type=ReportType.COVERAGE.value,
            )
            db_session.add(current_report_row)
            db_session.flush()
            report_details = (
                db_session.query(ReportDetails)
                .filter_by(report_id=current_report_row.id_)
                .first()
            )
            if report_details is None:
                report_details = ReportDetails(
                    report_id=current_report_row.id_,
                    _files_array=[],
                    report=current_report_row,
                )
                db_session.add(report_details)
                db_session.flush()

            actual_report = self.get_existing_report_for_commit_from_legacy_data(
                commit, report_code=report_code
            )
            if actual_report is not None:
                log.info(
                    "Backfilling reports tables from commits.report",
                    extra=dict(commitid=commit.commitid),
                )
                # This case means the report exists in our system, it was just not saved
                #   yet into the new models therefore it needs backfilling
                self.save_full_report(commit, actual_report)
        elif current_report_row.details is None:
            report_details = ReportDetails(
                report_id=current_report_row.id_,
                _files_array=[],
                report=current_report_row,
            )
            db_session.add(report_details)
            db_session.flush()
        if not self.has_initialized_report(commit):
            report = self.create_new_report_for_commit(commit)
            if not report.is_empty():
                # This means there is a report to carryforward
                self.save_full_report(commit, report, report_code)

                # Behind parallel processing flag, save the CFF report to GCS so the parallel variant of
                # finisher can build off of it later.
                if PARALLEL_UPLOAD_PROCESSING_BY_REPO.check_value(
                    identifier=commit.repository.repoid
                ):
                    self.save_parallel_report_to_archive(commit, report, report_code)

        return current_report_row

    def create_report_upload(
        self, normalized_arguments: Mapping[str, str], commit_report: CommitReport
    ) -> Upload:
        upload = super().create_report_upload(normalized_arguments, commit_report)
        flags = normalized_arguments.get("flags", "").split(",")
        self._attach_flags_to_upload(upload, flags)

        # Insert entry in user measurements table only
        # for reports with coverage type
        commit = commit_report.commit
        repository = commit.repository
        owner = repository.owner

        insert_coverage_measurement(
            owner_id=owner.ownerid,
            repo_id=repository.repoid,
            commit_id=commit.id,
            upload_id=upload.id,
            # CLI precreates the upload in API so this defaults to Legacy
            uploader_used=UploaderType.LEGACY.value,
            private_repo=repository.private,
            report_type=commit_report.report_type,
        )

        return upload

    def _attach_flags_to_upload(self, upload: Upload, flag_names: Sequence[str]):
        """Internal function that manages creating the proper `RepositoryFlag`s and attach the sessions to them

        Args:
            upload (Upload): Description
            flag_names (Sequence[str]): Description

        Returns:
            TYPE: Description
        """
        all_flags = []
        db_session = upload.get_db_session()
        repoid = upload.report.commit.repoid

        if self.flag_dict is None:
            self.fetch_repo_flags(db_session, repoid)

        for individual_flag in flag_names:
            flag_obj = self.flag_dict.get(individual_flag, None)
            if flag_obj is None:
                flag_obj = RepositoryFlag(
                    repository_id=repoid, flag_name=individual_flag
                )
                db_session.add(flag_obj)
                db_session.flush()
                self.flag_dict[individual_flag] = flag_obj
            all_flags.append(flag_obj)
        upload.flags = all_flags
        db_session.flush()
        return all_flags

    def fetch_repo_flags(self, db_session, repoid):
        existing_flags_on_repo = (
            db_session.query(RepositoryFlag).filter_by(repository_id=repoid).all()
        )
        self.flag_dict = {flag.flag_name: flag for flag in existing_flags_on_repo}

    def build_files(
        self, report_details: ReportDetails
    ) -> dict[str, ReportFileSummary]:
        return {
            file["filename"]: ReportFileSummary(
                file_index=file["file_index"],
                file_totals=ReportTotals(*file["file_totals"]),
                diff_totals=file["diff_totals"],
            )
            for file in report_details.files_array
        }

    def build_totals(self, totals: AbstractTotals) -> ReportTotals:
        """
        Build a `shared.reports.types.ReportTotals` instance from one of the
        various database totals records.
        """
        return ReportTotals(
            files=totals.files,
            lines=totals.lines,
            hits=totals.hits,
            misses=totals.misses,
            partials=totals.partials,
            coverage=totals.coverage,
            branches=totals.branches,
            methods=totals.methods,
        )

    def build_session(self, upload: Upload):
        """
        Build a `shared.utils.sessions.Session` from a database `reports_upload` record.
        """
        totals = self.build_totals(upload.totals) if upload.totals is not None else None

        return Session(
            id=upload.order_number,
            totals=totals,
            time=int(upload.created_at.timestamp()),
            archive=upload.storage_path,
            flags=upload.flag_names,
            provider=upload.provider,
            build=upload.build_code,
            job=upload.job_code,
            url=upload.build_url,
            state=upload.state,
            env=upload.env,
            name=upload.name,
            session_type=SessionType.get_from_string(upload.upload_type),
            session_extras=upload.upload_extras,
        )

    def build_sessions(self, commit: Commit) -> dict[int, Session]:
        """
        Build mapping of report number -> session that can be passed to the report class.
        Does not include CF sessions if there is also an upload session with the same
        flag name.
        """
        sessions = {}

        carryforward_sessions = {}
        uploaded_flags = set()

        commit_report = commit.report
        if not commit_report:
            log.warning("Missing commit report", extra=dict(commit=commit.commitid))
            return sessions

        db_session = commit.get_db_session()
        report_uploads = db_session.query(Upload).filter(
            (Upload.report_id == commit_report.id_)
            & ((Upload.state == "processed") | (Upload.state == "complete"))
        )

        for upload in report_uploads:
            session = self.build_session(upload)
            if session.session_type == SessionType.carriedforward:
                carryforward_sessions[upload.order_number] = session
            else:
                sessions[upload.order_number] = session
                uploaded_flags |= set(session.flags)

        for sid, session in carryforward_sessions.items():
            overlapping_flags = uploaded_flags & set(session.flags)
            if len(overlapping_flags) == 0 or self._is_labels_flags(overlapping_flags):
                # we can include this CF session since there are no direct uploads
                # with the same flag name OR we're carrying forward labels
                sessions[sid] = session

        log.info(
            "Building report sessions from upload records",
            extra=dict(
                commit=commit.commitid,
                upload_count=report_uploads.count(),
                session_ids=list(sessions.keys()),
            ),
        )

        return sessions

    @sentry_sdk.trace
    def build_report(
        self, chunks, files, sessions, totals, report_class=None
    ) -> Report:
        if report_class is None:
            report_class = Report
            for sess in sessions.values():
                if isinstance(sess, Session):
                    if sess.session_type == SessionType.carriedforward:
                        report_class = EditableReport
                else:
                    # sess is an encoded dict
                    if sess.get("st") == "carriedforward":
                        report_class = EditableReport
        with metrics.timer(
            f"services.report.ReportService.build_report.{report_class.__name__}"
        ):
            return report_class.from_chunks(
                chunks=chunks, files=files, sessions=sessions, totals=totals
            )

    def get_archive_service(self, repository: Repository) -> ArchiveService:
        return ArchiveService(repository)

    def build_report_from_commit(self, commit) -> Report:
        report = self.get_existing_report_for_commit(commit)
        if report is not None:
            return report
        return self.create_new_report_for_commit(commit)

    def get_existing_report_for_commit_from_legacy_data(
        self, commit: Commit, report_class=None, *, report_code=None
    ) -> Optional[Report]:
        commitid = commit.commitid
        if commit._report_json is None and commit._report_json_storage_path is None:
            return None
        try:
            archive_service = self.get_archive_service(commit.repository)
            chunks = archive_service.read_chunks(commitid, report_code)
        except FileNotInStorageError:
            log.warning(
                "File for chunks not found in storage",
                extra=dict(
                    commit=commitid, repo=commit.repoid, report_code=report_code
                ),
            )
            return None
        if chunks is None:
            return None
        files = commit.report_json["files"]
        sessions = commit.report_json["sessions"]
        totals = commit.totals
        res = self.build_report(
            chunks, files, sessions, totals, report_class=report_class
        )
        return res

    def _is_labels_flags(self, flags: Sequence[str]) -> bool:
        return len(flags) > 0 and all(
            [
                (self.current_yaml.get_flag_configuration(flag) or {}).get(
                    "carryforward_mode"
                )
                == "labels"
                for flag in flags
            ]
        )

    @sentry_sdk.trace
    def get_existing_report_for_commit(
        self, commit: Commit, report_class=None, *, report_code=None
    ) -> Optional[Report]:
        commit_report = commit.report
        if commit_report is None:
            log.warning(
                "Building report from legacy data",
                extra=dict(commitid=commit.commitid),
            )
            return self.get_existing_report_for_commit_from_legacy_data(
                commit, report_class=report_class, report_code=report_code
            )

        # TODO: this can be removed once confirmed working well on prod
        report_builder_repo_ids = get_config(
            "setup", "report_builder", "repo_ids", default=[]
        )
        new_report_builder_enabled = (
            get_current_env() == Environment.local
            or commit.repoid in report_builder_repo_ids
        )
        if not new_report_builder_enabled:
            return self.get_existing_report_for_commit_from_legacy_data(
                commit, report_class=report_class, report_code=report_code
            )

        commitid = commit.commitid
        totals = None
        files = {}
        sessions = self.build_sessions(commit)
        if commit_report.details:
            files = self.build_files(commit_report.details)
        if commit_report.totals:
            totals = self.build_totals(commit_report.totals)
        try:
            archive_service = self.get_archive_service(commit.repository)
            chunks = archive_service.read_chunks(commitid, report_code)
        except FileNotInStorageError:
            log.warning(
                "File for chunks not found in storage",
                extra=dict(
                    commit=commitid, repo=commit.repoid, report_code=report_code
                ),
            )
            return None
        if chunks is None:
            return None

        report = self.build_report(
            chunks, files, sessions, totals, report_class=report_class
        )

        sessions_to_delete = []
        for sid, session in report.sessions.items():
            # this mimics behavior in the `adjust_sessions` function from
            # `services/report/raw_upload_processor.py` - we need to delete
            # label sessions for which there are no labels
            # TODO: ultimately use `reports_upload.state` once the
            # `PARTIALLY_OVERWRITTEN` and `FULLY_OVERWRITTEN` states are being saved
            labels_session = self._is_labels_flags(session.flags)
            if labels_session:
                labels = get_labels_per_session(report, sid)
                if not labels:
                    sessions_to_delete.append(sid)

        if len(sessions_to_delete) > 0:
            log.info(
                "Deleting empty labels sessions",
                extra=dict(commit=commit.commitid, session_ids=sessions_to_delete),
            )
            for sid in sessions_to_delete:
                del sessions[sid]

            # rebuild the report since we deleted some sessions
            report = self.build_report(
                chunks, files, sessions, totals, report_class=report_class
            )

        return report

    @metrics.timer(
        "services.report.ReportService.get_appropriate_commit_to_carryforward_from"
    )
    def get_appropriate_commit_to_carryforward_from(
        self, commit: Commit, max_parenthood_deepness: int = 10
    ) -> Optional[Commit]:
        parent_commit = commit.get_parent_commit()
        parent_commit_tracking = []
        count = 1  # `parent_commit` is already the first parent
        while (
            parent_commit is not None
            and parent_commit.state not in ("complete", "skipped")
            and count < max_parenthood_deepness
        ):
            parent_commit_tracking.append(parent_commit.commitid)
            if (
                parent_commit.state == "pending"
                and parent_commit.parent_commit_id is None
            ):
                log.warning(
                    "One of the ancestors commit doesn't seem to have determined its parent yet",
                    extra=dict(
                        commit=commit.commitid,
                        repoid=commit.repoid,
                        current_parent_commit=parent_commit.commitid,
                    ),
                )
                raise NotReadyToBuildReportYetError()
            log.info(
                "Going from parent to their parent since they dont match the requisites for CFF",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    current_parent_commit=parent_commit.commitid,
                    parent_tracking=parent_commit_tracking,
                    current_state=parent_commit.state,
                    new_parent_commit=parent_commit.parent_commit_id,
                ),
            )
            parent_commit = parent_commit.get_parent_commit()
            count += 1
        if parent_commit is None:
            log.warning(
                "No parent commit was found to be carriedforward from",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    parent_tracing=parent_commit_tracking,
                ),
            )
            return None
        if parent_commit.state not in ("complete", "skipped"):
            log.warning(
                "None of the parent commits were in a complete state to be used as CFing base",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    parent_tracking=parent_commit_tracking,
                    would_be_state=parent_commit.state,
                    would_be_parent=parent_commit.commitid,
                ),
            )
            return None
        return parent_commit

    def _possibly_shift_carryforward_report(
        self, carryforward_report: Report, base_commit: Commit, head_commit: Commit
    ) -> Report:
        with metrics.timer(
            "services.report.ReportService.possibly_shift_carryforward_report"
        ):
            try:
                provider_service: TorngitBaseAdapter = get_repo_provider_service(
                    repository=head_commit.repository,
                    installation_name_to_use=self.gh_app_installation_name,
                )
                diff = (
                    async_to_sync(provider_service.get_compare)(
                        base=base_commit.commitid, head=head_commit.commitid
                    )
                )["diff"]
                # Volatile function, alters carryforward_report
                carryforward_report.shift_lines_by_diff(diff)
            except (RepositoryWithoutValidBotError, OwnerWithoutValidBotError) as exp:
                log.error(
                    "Failed to shift carryforward report lines",
                    extra=dict(
                        reason="Can't get provider_service",
                        commit=head_commit.commitid,
                        error=str(exp),
                    ),
                )
            except TorngitError as exp:
                log.error(
                    "Failed to shift carryforward report lines.",
                    extra=dict(
                        reason="Can't get diff",
                        commit=head_commit.commitid,
                        error=str(exp),
                        error_type=type(exp),
                    ),
                )
            except SoftTimeLimitExceeded:
                raise
            except Exception:
                log.exception(
                    "Failed to shift carryforward report lines.",
                    extra=dict(
                        reason="Unknown",
                        commit=head_commit.commitid,
                    ),
                )
            return carryforward_report

    def create_new_report_for_commit(self, commit: Commit) -> Report:
        with metrics.timer(
            "services.report.ReportService.create_new_report_for_commit"
        ):
            log.info(
                "Creating new report for commit",
                extra=dict(commit=commit.commitid, repoid=commit.repoid),
            )
            if not self.current_yaml:
                return Report()
            if not self.current_yaml.has_any_carryforward():
                return Report()

            repo = commit.repository
            metric_context = MetricContext(
                commit_sha=commit.commitid,
                commit_id=commit.id,
                repo_id=commit.repoid,
                owner_id=repo.ownerid,
            )

            # This experiment is inactive because the data went back and forth
            # on whether it was impactful or not. The `Feature` is left here as
            # a knob to turn for support requests about carryforward flags, and
            # maybe we'll revisit a general rollout at a later time.
            max_parenthood_deepness = (
                CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER.check_value(
                    identifier=repo.ownerid, default=10
                )
            )

            parent_commit = self.get_appropriate_commit_to_carryforward_from(
                commit, max_parenthood_deepness
            )
            if parent_commit is None:
                log.warning(
                    "Could not find parent for possible carryforward",
                    extra=dict(commit=commit.commitid, repoid=commit.repoid),
                )
                metric_context.log_simple_metric(
                    "worker_service_report_carryforward_base_not_found", 1
                )
                return Report()

            parent_report = self.get_existing_report_for_commit(parent_commit)
            if parent_report is None:
                log.warning(
                    "Could not carryforward report from another commit because parent has no report",
                    extra=dict(
                        commit=commit.commitid,
                        repoid=commit.repoid,
                        parent_commit=parent_commit.commitid,
                    ),
                )
                return Report()

            flags_to_carryforward = [
                flag_name
                for flag_name in parent_report.get_flag_names()
                if self.current_yaml.flag_has_carryfoward(flag_name)
            ]
            if not flags_to_carryforward:
                return Report()

            paths_to_carryforward = get_paths_from_flags(
                self.current_yaml, flags_to_carryforward
            )
            log.info(
                "Generating carriedforward report",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    parent_commit=parent_commit.commitid,
                    flags_to_carryforward=flags_to_carryforward,
                    paths_to_carryforward=paths_to_carryforward,
                    parent_sessions=parent_report.sessions,
                ),
            )
            carryforward_report = generate_carryforward_report(
                parent_report,
                flags_to_carryforward,
                paths_to_carryforward,
                session_extras=dict(carriedforward_from=parent_commit.commitid),
            )
            # If the parent report has labels we also need to carryforward the label index
            # Considerations:
            #   1. It's necessary for labels flags to be carryforward, so it's ok to carryforward the entire index
            #   2. As tests are renamed the index might start to be filled with stale labels. This is not good.
            #      but I'm unsure if we should try to clean it up at this point. Cleaning it up requires going through
            #      all lines of the report. It will be handled by a dedicated task that is encoded by the UploadFinisher
            #   3. We deepcopy the header so we can change them independently
            #   4. The parent_commit always uses the default report to carryforward (i.e. report_code for parent_commit is None)
            # parent_commit and commit should belong to the same repository
            carryforward_report.header = copy.deepcopy(parent_report.header)

            self._possibly_shift_carryforward_report(
                carryforward_report, parent_commit, commit
            )
            metric_context.log_simple_metric(
                "worker_service_report_carryforward_success", 1
            )
            return carryforward_report

    @sentry_sdk.trace
    def parse_raw_report_from_storage(
        self, repo: Repository, upload: Upload
    ) -> ParsedRawReport:
        """Pulls the raw uploaded report from storage and parses it so it's
        easier to access different parts of the raw upload.

        Raises:
            shared.storage.exceptions.FileNotInStorageError
        """
        archive_service = self.get_archive_service(repo)
        archive_url = upload.storage_path

        log.info(
            "Parsing the raw report from storage",
            extra=dict(
                commit=upload.report.commit_id,
                repoid=repo.repoid,
                archive_url=archive_url,
            ),
        )

        archive_file = archive_service.read_file(archive_url)

        parser = get_proper_parser(upload, archive_file)
        upload_version = (
            "v1" if isinstance(parser, VersionOneReportParser) else "legacy"
        )
        RAW_UPLOAD_SIZE.labels(version=upload_version).observe(len(archive_file))

        raw_uploaded_report = parser.parse_raw_report_from_bytes(archive_file)

        raw_report_count = len(raw_uploaded_report.get_uploaded_files())
        if raw_report_count < 1:
            log.warning(
                "Raw upload contains no uploaded files",
                extra=dict(
                    commit=upload.report.commit_id,
                    repoid=repo.repoid,
                    raw_report_count=raw_report_count,
                    upload_version=upload_version,
                    archive_url=archive_url,
                ),
            )
        RAW_UPLOAD_RAW_REPORT_COUNT.labels(version=upload_version).observe(
            raw_report_count
        )

        return raw_uploaded_report

    @sentry_sdk.trace
    def build_report_from_raw_content(
        self,
        report: Report,
        raw_report_info: RawReportInfo,
        upload: Upload,
        parallel_idx=None,
    ) -> ProcessingResult:
        """
        Processes an upload on top of an existing report `master` and returns
        a result, which could be successful or not

        Note that this function does not modify the `upload` object, as this should
        be done by a separate function
        """
        commit = upload.report.commit
        flags = upload.flag_names
        service = upload.provider
        build_url = upload.build_url
        build = upload.build_code
        job = upload.job_code
        name = upload.name
        archive_url = upload.storage_path
        reportid = upload.external_id

        session = Session(
            provider=service,
            build=build,
            job=job,
            name=name,
            time=int(time()),
            flags=flags,
            archive=archive_url,
            url=build_url,
        )
        result = ProcessingResult(session=session)

        raw_report_info.archive_url = archive_url
        raw_report_info.upload = upload.external_id

        try:
            raw_report = self.parse_raw_report_from_storage(commit.repository, upload)
            raw_report_info.raw_report = raw_report
        except FileNotInStorageError:
            log.info(
                "Raw report file was not found",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    reportid=reportid,
                    commit_yaml=self.current_yaml.to_dict(),
                    archive_url=archive_url,
                    in_parallel=parallel_idx is not None,
                ),
            )
            result.error = ProcessingError(
                code=UploadErrorCode.FILE_NOT_IN_STORAGE,
                params={"location": archive_url},
                is_retryable=True,
            )
            raw_report_info.error = result.error
            return result
        except Exception as e:
            log.exception(
                "Unknown error when fetching raw report from storage",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    archive_path=archive_url,
                ),
            )
            result.error = ProcessingError(
                code=UploadErrorCode.UNKNOWN_STORAGE,
                params={"location": archive_url},
                is_retryable=False,
            )
            raw_report_info.error = result.error
            return result

        log.debug("Retrieved report for processing from url %s", archive_url)
        try:
            with metrics.timer(f"{self.metrics_prefix}.process_report") as t:
                process_result = process_raw_upload(
                    self.current_yaml,
                    report,
                    raw_report,
                    flags,
                    session,
                    upload=upload,
                    parallel_idx=parallel_idx,
                )
                result.report = process_result.report
            log.info(
                "Successfully processed report"
                + (" (in parallel)" if parallel_idx is not None else ""),
                extra=dict(
                    session=session.id,
                    ci=f"{session.provider}:{session.build}:{session.job}",
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    reportid=reportid,
                    commit_yaml=self.current_yaml.to_dict(),
                    timing_ms=t.ms,
                    content_len=raw_report.size,
                ),
            )
            return result
        except ReportExpiredException as r:
            log.info(
                "Report %s is expired",
                reportid,
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    archive_path=archive_url,
                    file_name=r.filename,
                ),
            )
            result.error = ProcessingError(
                code=UploadErrorCode.REPORT_EXPIRED, params={}
            )
            raw_report_info.error = result.error
            return result
        except ReportEmptyError:
            log.warning(
                "Report %s is empty",
                reportid,
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            result.error = ProcessingError(code=UploadErrorCode.REPORT_EMPTY, params={})
            raw_report_info.error = result.error
            return result
        except Exception as e:
            log.exception(
                "Unknown error when processing raw upload",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    archive_path=archive_url,
                ),
            )
            result.error = ProcessingError(
                code=UploadErrorCode.UNKNOWN_PROCESSING,
                params={"location": archive_url},
                is_retryable=False,
            )
            raw_report_info.error = result.error
            return result

    def update_upload_with_processing_result(
        self, upload_obj: Upload, processing_result: ProcessingResult
    ):
        rounding: str = read_yaml_field(
            self.current_yaml, ("coverage", "round"), "nearest"
        )
        precision: int = read_yaml_field(
            self.current_yaml, ("coverage", "precision"), 2
        )
        db_session = upload_obj.get_db_session()
        session = processing_result.session
        if processing_result.error is None:
            # this should be enabled for the actual rollout of parallel upload processing.
            # if PARALLEL_UPLOAD_PROCESSING_BY_REPO.check_value(
            #     "this should be the repo id"
            # ):
            #     upload_obj.state_id = UploadState.PARALLEL_PROCESSED.db_id
            #     upload_obj.state = "parallel_processed"
            # else:
            upload_obj.state_id = UploadState.PROCESSED.db_id
            upload_obj.state = "processed"
            upload_obj.order_number = session.id
            upload_totals = upload_obj.totals
            if upload_totals is None:
                upload_totals = UploadLevelTotals(
                    upload_id=upload_obj.id,
                    branches=0,
                    coverage=0,
                    hits=0,
                    lines=0,
                    methods=0,
                    misses=0,
                    partials=0,
                    files=0,
                )
                db_session.add(upload_totals)
            if session.totals is not None:
                upload_totals.update_from_totals(
                    session.totals, precision=precision, rounding=rounding
                )
        else:
            error = processing_result.error
            upload_obj.state = "error"
            upload_obj.state_id = UploadState.ERROR.db_id
            error_obj = UploadError(
                upload_id=upload_obj.id,
                error_code=error.code,
                error_params=error.params,
            )
            db_session.add(error_obj)
            db_session.flush()

    @sentry_sdk.trace
    def save_report(self, commit: Commit, report: Report, report_code=None):
        if len(report._chunks) > 2 * len(report._files) and len(report._files) > 0:
            report.repack()
        archive_service = self.get_archive_service(commit.repository)

        totals, report_json = report.to_database()

        archive_data = report.to_archive().encode()
        chunks_url = archive_service.write_chunks(
            commit.commitid, archive_data, report_code
        )

        commit.state = "complete" if report else "error"
        commit.totals = totals
        if (
            commit.totals is not None
            and "c" in commit.totals
            and commit.totals["c"] is None
        ):
            # temporary measure until we ensure the API and frontend don't expect not-null coverages
            commit.totals["c"] = 0

        log.info(
            "Calling update to Commit.Report",
            extra=dict(
                size=len(report_json),
                ownerid=commit.repository.ownerid,
                repoid=commit.repoid,
                commitid=commit.commitid,
            ),
        )
        # `report_json` is an `ArchiveField`, so this will trigger an upload
        # FIXME: we do an unnecessary `loads` roundtrip because of this abstraction,
        # and we should just save the `report_json` to archive storage directly instead.
        commit.report_json = loads(report_json)

        # `report` is an accessor which implicitly queries `CommitReport`
        if commit_report := commit.report:
            files_array = [
                {
                    "filename": k,
                    "file_index": v.file_index,
                    "file_totals": v.file_totals,
                    "diff_totals": v.diff_totals,
                }
                for k, v in report._files.items()
            ]
            log.info(
                "Calling update to reports_reportdetails.files_array",
                extra=dict(
                    size=sys.getsizeof(files_array),
                    ownerid=commit.repository.ownerid,
                    repoid=commit.repoid,
                    commitid=commit.commitid,
                ),
            )
            db_session = commit.get_db_session()

            # `files_array` is an `ArchiveField`, so this will trigger an upload
            commit_report.details.files_array = files_array
            report_totals = commit_report.totals
            if report_totals is None:
                report_totals = ReportLevelTotals(report_id=commit_report.id)
                db_session.add(report_totals)

            rounding: str = read_yaml_field(
                self.current_yaml, ("coverage", "round"), "nearest"
            )
            precision: int = read_yaml_field(
                self.current_yaml, ("coverage", "precision"), 2
            )
            report_totals.update_from_totals(
                report.totals, precision=precision, rounding=rounding
            )
            db_session.flush()
        log.info(
            "Archived report",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
                url=chunks_url,
                number_sessions=len(report.sessions),
                new_report_sessions=dict(itertools.islice(report.sessions.items(), 20)),
            ),
        )
        return {"url": chunks_url}

    @sentry_sdk.trace
    def save_full_report(
        self, commit: Commit, report: Report, report_code=None
    ) -> dict:
        """
        Saves the report (into database and storage) AND takes care of backfilling its sessions
        like they were never in the database (useful for backfilling and carryforward cases)
        """
        rounding: str = read_yaml_field(
            self.current_yaml, ("coverage", "round"), "nearest"
        )
        precision: int = read_yaml_field(
            self.current_yaml, ("coverage", "precision"), 2
        )
        res = self.save_report(commit, report, report_code)
        db_session = commit.get_db_session()
        for sess_id, session in report.sessions.items():
            upload = Upload(
                build_code=session.build,
                build_url=session.url,
                env=session.env,
                external_id=uuid.uuid4(),
                job_code=session.job,
                name=session.name[:100] if session.name is not None else None,
                order_number=sess_id,
                provider=session.provider,
                report_id=commit.report.id_,
                state="complete",
                storage_path=session.archive if session.archive is not None else "",
                upload_extras=session.session_extras or {},
                upload_type=(
                    session.session_type.value
                    if session.session_type is not None
                    else "unknown"
                ),
            )
            db_session.add(upload)
            db_session.flush()
            self._attach_flags_to_upload(upload, session.flags if session.flags else [])
            if session.totals is not None:
                upload_totals = UploadLevelTotals(upload_id=upload.id_)
                db_session.add(upload_totals)
                upload_totals.update_from_totals(
                    session.totals, precision=precision, rounding=rounding
                )
        return res

    @sentry_sdk.trace
    def save_parallel_report_to_archive(
        self, commit: Commit, report: Report, report_code=None
    ):
        commitid = commit.commitid
        repository = commit.repository
        archive_service = self.get_archive_service(commit.repository)

        # Attempt to calculate diff of report (which uses commit info from the git provider), but it it fails to do so, it just moves on without such diff
        try:
            repository_service: TorngitBaseAdapter = get_repo_provider_service(
                repository,
                installation_name_to_use=self.gh_app_installation_name,
            )
            diff = async_to_sync(repository_service.get_commit_diff)(commitid)
            report.apply_diff(diff)
        except TorngitError:
            # When this happens, we have that commit.totals["diff"] is not available.
            # Since there is no way to calculate such diff without the git commit,
            # then we assume having the rest of the report saved there is better than the
            # alternative of refusing an otherwise "good" report because of the lack of diff
            log.warning(
                "Could not apply diff to report because there was an error fetching diff from provider",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    parent_task=self.request.parent_id,
                ),
                exc_info=True,
            )

        # save incremental results to archive storage,
        # upload_finisher will combine
        chunks = report.to_archive().encode()
        _, files_and_sessions = report.to_database()

        chunks_url = archive_service.write_parallel_experiment_file(
            commitid, chunks, report_code, "chunks"
        )

        files_and_sessions_url = archive_service.write_parallel_experiment_file(
            commitid, files_and_sessions, report_code, "files_and_sessions"
        )

        return {
            "chunks_path": chunks_url,
            "files_and_sessions_path": files_and_sessions_url,
        }
