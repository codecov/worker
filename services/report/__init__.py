import copy
import itertools
import logging
import uuid
from dataclasses import dataclass
from time import time
from typing import Any

import orjson
import sentry_sdk
from asgiref.sync import async_to_sync
from celery.exceptions import SoftTimeLimitExceeded
from shared.django_apps.reports.models import ReportType
from shared.reports.carryforward import generate_carryforward_report
from shared.reports.editable import EditableReport
from shared.reports.enums import UploadState, UploadType
from shared.reports.resources import Report
from shared.reports.types import TOTALS_MAP
from shared.storage.exceptions import FileNotInStorageError
from shared.torngit.exceptions import TorngitError
from shared.upload.constants import UploadErrorCode
from shared.utils.sessions import Session, SessionType
from shared.yaml import UserYaml
from sqlalchemy.orm import Session as DbSession

from database.models import Commit, Repository, Upload, UploadError
from database.models.reports import (
    CommitReport,
    ReportLevelTotals,
    RepositoryFlag,
    UploadLevelTotals,
    uploadflagmembership,
)
from helpers.exceptions import (
    OwnerWithoutValidBotError,
    ReportEmptyError,
    ReportExpiredException,
    RepositoryWithoutValidBotError,
)
from rollouts import CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER
from services.archive import ArchiveService
from services.processing.metrics import (
    PYREPORT_CHUNKS_FILE_SIZE,
    PYREPORT_REPORT_JSON_SIZE,
)
from services.processing.types import ProcessingErrorDict, UploadArguments
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

    def as_dict(self) -> ProcessingErrorDict:
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

    def __init__(self, current_yaml: UserYaml | dict):
        if isinstance(current_yaml, dict):
            current_yaml = UserYaml(current_yaml)
        self.current_yaml = current_yaml

    def initialize_and_save_report(
        self, commit: Commit, report_code: str | None = None
    ) -> CommitReport:
        raise NotImplementedError()

    def create_report_upload(
        self, arguments: UploadArguments, commit_report: CommitReport
    ) -> Upload:
        """
        Creates an `Upload` from the user-given arguments to a job

        The end goal here is that the `Upload` should have all the information needed to
        hypothetically redo the job later.
        """
        db_session = commit_report.get_db_session()
        name = arguments.get("name")
        upload = Upload(
            report_id=commit_report.id_,
            external_id=arguments.get("reportid"),
            build_code=arguments.get("build"),
            build_url=arguments.get("build_url"),
            env=None,
            job_code=arguments.get("job"),
            name=(name[:100] if name else None),
            provider=arguments.get("service"),
            state="started",
            storage_path=arguments.get("url"),
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
    def __init__(
        self, current_yaml: UserYaml | dict, gh_app_installation_name: str | None = None
    ):
        super().__init__(current_yaml)
        self.flag_dict: dict[str, RepositoryFlag] | None = None
        self.gh_app_installation_name = gh_app_installation_name

    def has_initialized_report(self, commit: Commit) -> bool:
        """
        Says whether a commit has already initialized its report or not
        """
        return (
            commit._report_json is not None
            or commit._report_json_storage_path is not None
        )

    @sentry_sdk.trace
    def initialize_and_save_report(
        self, commit: Commit, report_code: str | None = None
    ) -> CommitReport:
        """
            Initializes the commit report


            This is one of the main entrypoint of this class. It takes care of:
                - Creating the `CommitReport`, if needed
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

            actual_report = self.get_existing_report_for_commit(
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

        if not self.has_initialized_report(commit):
            report = self.create_new_report_for_commit(commit)
            if not report.is_empty():
                # This means there is a report to carryforward
                self.save_full_report(commit, report, report_code)

        return current_report_row

    def _attach_flags_to_upload(self, upload: Upload, flag_names: list[str]):
        """
        Internal function that manages creating the proper `RepositoryFlag`s,
        and attach them to the `Upload`
        """

        all_flags = []
        db_session = upload.get_db_session()
        repoid = upload.report.commit.repoid
        flag_dict = self.fetch_repo_flags(db_session, repoid)

        for individual_flag in flag_names:
            flag_obj = flag_dict.get(individual_flag, None)
            if flag_obj is None:
                flag_obj = RepositoryFlag(
                    repository_id=repoid, flag_name=individual_flag
                )
                db_session.add(flag_obj)
                db_session.flush()
                flag_dict[individual_flag] = flag_obj
            all_flags.append(flag_obj)

        upload.flags = all_flags
        db_session.flush()
        return all_flags

    def fetch_repo_flags(self, db_session, repoid: int) -> dict[str, RepositoryFlag]:
        if self.flag_dict is None:
            existing_flags_on_repo = (
                db_session.query(RepositoryFlag).filter_by(repository_id=repoid).all()
            )
            self.flag_dict = {flag.flag_name: flag for flag in existing_flags_on_repo}
        return self.flag_dict

    @sentry_sdk.trace
    def build_report(
        self, chunks, files, sessions: dict, totals, report_class=None
    ) -> Report:
        if report_class is None:
            report_class = Report
            for session_id, session in sessions.items():
                if isinstance(session, Session):
                    if session.session_type == SessionType.carriedforward:
                        report_class = EditableReport
                else:
                    # make sure the `Session` objects get an `id` when decoded:
                    session["id"] = int(session_id)
                    if session.get("st") == "carriedforward":
                        report_class = EditableReport

        return report_class.from_chunks(
            chunks=chunks, files=files, sessions=sessions, totals=totals
        )

    def get_archive_service(self, repository: Repository) -> ArchiveService:
        return ArchiveService(repository)

    @sentry_sdk.trace
    def get_existing_report_for_commit(
        self, commit: Commit, report_class=None, report_code=None
    ) -> Report | None:
        commitid = commit.commitid
        if not self.has_initialized_report(commit):
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

    def get_appropriate_commit_to_carryforward_from(
        self, commit: Commit, max_parenthood_deepness: int = 10
    ) -> Commit | None:
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
        try:
            provider_service = get_repo_provider_service(
                repository=head_commit.repository,
                installation_name_to_use=self.gh_app_installation_name,
            )
            diff = async_to_sync(provider_service.get_compare)(
                base=base_commit.commitid, head=head_commit.commitid
            )
            # Volatile function, alters carryforward_report
            carryforward_report.shift_lines_by_diff(diff["diff"])
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
        log.info(
            "Creating new report for commit",
            extra=dict(commit=commit.commitid, repoid=commit.repoid),
        )
        if not self.current_yaml:
            return Report()
        if not self.current_yaml.has_any_carryforward():
            return Report()

        repo = commit.repository
        # This experiment is inactive because the data went back and forth
        # on whether it was impactful or not. The `Feature` is left here as
        # a knob to turn for support requests about carryforward flags, and
        # maybe we'll revisit a general rollout at a later time.
        max_parenthood_deepness = CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER.check_value(
            identifier=repo.ownerid, default=10
        )

        parent_commit = self.get_appropriate_commit_to_carryforward_from(
            commit, max_parenthood_deepness
        )
        if parent_commit is None:
            log.warning(
                "Could not find parent for possible carryforward",
                extra=dict(commit=commit.commitid, repoid=commit.repoid),
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
        raw_report_info: RawReportInfo,
        upload: Upload,
    ) -> ProcessingResult:
        """
        Processes an upload on top of an existing report `master` and returns
        a result, which could be successful or not

        Note that this function does not modify the `upload` object, as this should
        be done by a separate function
        """
        commit = upload.report.commit
        flags = upload.flag_names
        archive_url = upload.storage_path
        reportid = upload.external_id

        session = Session(
            provider=upload.provider,
            build=upload.build_code,
            job=upload.job_code,
            name=upload.name,
            time=int(time()),
            flags=flags,
            archive=archive_url,
            url=upload.build_url,
        )
        result = ProcessingResult(session=session)

        raw_report_info.archive_url = archive_url
        raw_report_info.upload = upload.external_id

        try:
            raw_report = self.parse_raw_report_from_storage(commit.repository, upload)
            raw_report_info.raw_report = raw_report
        except FileNotInStorageError as e:
            sentry_sdk.capture_exception(e)
            log.info(
                "Raw report file was not found",
                extra=dict(
                    reportid=reportid,
                    commit_yaml=self.current_yaml.to_dict(),
                    archive_url=archive_url,
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
            sentry_sdk.capture_exception(e)
            log.exception(
                "Unknown error when fetching raw report from storage",
                extra=dict(archive_path=archive_url),
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
            result.report = process_raw_upload(self.current_yaml, raw_report, session)

            log.info(
                "Successfully processed report",
                extra=dict(
                    session=session.id,
                    ci=f"{session.provider}:{session.build}:{session.job}",
                    reportid=reportid,
                    commit_yaml=self.current_yaml.to_dict(),
                    content_len=raw_report.size,
                ),
            )
            return result
        except ReportExpiredException as r:
            sentry_sdk.capture_exception(r)
            log.info(
                "Report is expired",
                extra=dict(
                    reportid=reportid, archive_path=archive_url, file_name=r.filename
                ),
            )
            result.error = ProcessingError(
                code=UploadErrorCode.REPORT_EXPIRED, params={}
            )
            raw_report_info.error = result.error
            return result
        except ReportEmptyError as e:
            sentry_sdk.capture_exception(e)
            log.warning("Report is empty", extra=dict(reportid=reportid))
            result.error = ProcessingError(code=UploadErrorCode.REPORT_EMPTY, params={})
            raw_report_info.error = result.error
            return result
        except SoftTimeLimitExceeded as e:
            sentry_sdk.capture_exception(e)
            log.warning(
                "Timed out while processing report", extra=dict(reportid=reportid)
            )
            result.error = ProcessingError(
                code=UploadErrorCode.PROCESSING_TIMEOUT, params={}
            )
            raw_report_info.error = result.error
            # Return and attempt to save the error result rather than re-raise
            return result
        except Exception as e:
            sentry_sdk.capture_exception(e)
            log.exception(
                "Unknown error when processing raw upload",
                extra=dict(archive_path=archive_url),
            )
            result.error = ProcessingError(
                code=UploadErrorCode.UNKNOWN_PROCESSING,
                params={"location": archive_url},
                is_retryable=False,
            )
            raw_report_info.error = result.error
            return result

    @sentry_sdk.trace
    def save_report(self, commit: Commit, report: Report, report_code=None):
        archive_service = self.get_archive_service(commit.repository)

        report_json, chunks, _totals = report.serialize()

        PYREPORT_REPORT_JSON_SIZE.observe(len(report_json))
        PYREPORT_CHUNKS_FILE_SIZE.observe(len(chunks))

        chunks_url = archive_service.write_chunks(commit.commitid, chunks, report_code)

        commit.state = "complete" if report else "error"
        commit.totals = legacy_totals(report)
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
        commit.report_json = orjson.loads(report_json)

        # `report` is an accessor which implicitly queries `CommitReport`
        if commit_report := commit.report:
            db_session = commit.get_db_session()

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
                db_session.flush()

        return res


@sentry_sdk.trace
def delete_uploads_by_sessionid(
    db_session: DbSession, report_id: int, session_ids: set[int]
):
    """
    This deletes all the `Upload` records belonging to the `CommitReport` with `report_id`,
    and having an `order_number` corresponding to the given `session_ids`.
    """
    uploads = (
        db_session.query(Upload.id_)
        .filter(
            Upload.report_id == report_id,
            Upload.upload_type == SessionType.carriedforward.value,
            Upload.order_number.in_(session_ids),
        )
        .all()
    )
    upload_ids = [upload[0] for upload in uploads]

    db_session.query(UploadError).filter(UploadError.upload_id.in_(upload_ids)).delete(
        synchronize_session=False
    )
    db_session.query(UploadLevelTotals).filter(
        UploadLevelTotals.upload_id.in_(upload_ids)
    ).delete(synchronize_session=False)
    db_session.query(uploadflagmembership).filter(
        uploadflagmembership.c.upload_id.in_(upload_ids)
    ).delete(synchronize_session=False)
    db_session.query(Upload).filter(Upload.id_.in_(upload_ids)).delete(
        synchronize_session=False
    )
    db_session.flush()


def legacy_totals(report: Report) -> dict:
    totals = dict(zip(TOTALS_MAP, report.totals))
    totals["diff"] = report.diff_totals
    return totals
