import itertools
import logging
import uuid
from dataclasses import dataclass
from json import loads
from time import time
from typing import Any, Dict, Mapping, Optional, Sequence

from shared.metrics import metrics
from shared.reports.carryforward import generate_carryforward_report
from shared.reports.editable import EditableReport
from shared.reports.enums import UploadState, UploadType
from shared.reports.resources import Report
from shared.storage.exceptions import FileNotInStorageError
from shared.utils.sessions import Session, SessionType

from database.models import Commit, Repository, Upload, UploadError
from database.models.reports import (
    CommitReport,
    ReportDetails,
    ReportLevelTotals,
    RepositoryFlag,
    UploadLevelTotals,
)
from helpers.exceptions import ReportEmptyError, ReportExpiredException
from services.archive import ArchiveService
from services.report.parser import RawReportParser
from services.report.raw_upload_processor import process_raw_upload
from services.yaml.reader import get_paths_from_flags


@dataclass
class ProcessingError(object):
    code: str
    params: Dict[str, Any]
    is_retryable: bool = False

    def as_dict(self):
        return {"code": self.code, "params": self.params}


@dataclass
class ProcessingResult(object):
    report: Optional[Report]
    session: Session
    error: Optional[ProcessingError]

    def as_dict(self):
        # Weird flow for now in order to keep things compatible with previous logging
        if self.error is not None:
            return {
                "successful": False,
                "error": self.error.as_dict(),
                "report": self.report,
                "should_retry": False,
            }
        return {"successful": True, "report": self.report}


log = logging.getLogger(__name__)


class NotReadyToBuildReportYetError(Exception):
    pass


class ReportService(object):

    metrics_prefix = "services.report"

    """This is the class that will handle anything report-handling related

    Attributes:
        current_yaml (Mapping[str, Any]): The configuration we need to follow.
            It's always the user yaml, but might have different uses on different places
    """

    def __init__(self, current_yaml: Mapping[str, Any]):
        self.current_yaml = current_yaml

    def has_initialized_report(self, commit: Commit) -> bool:
        """Says whether a commit has already initialized its report or not

        Args:
            commit (Commit): The commit we want to know about

        Returns:
            bool: Whether the commit already has initialized a report
        """
        return commit.report_json is not None

    def initialize_and_save_report(self, commit: Commit) -> CommitReport:
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
            db_session.query(CommitReport).filter_by(commit_id=commit.id_).first()
        )
        if not current_report_row:
            # This happens if the commit report is being created for the first time
            # or backfilled
            current_report_row = CommitReport(commit_id=commit.id_)
            db_session.add(current_report_row)
            db_session.flush()
            report_details = (
                db_session.query(ReportDetails)
                .filter_by(report_id=current_report_row.id_)
                .first()
            )
            if report_details is None:
                report_details = ReportDetails(
                    report_id=current_report_row.id_, files_array=[]
                )
                db_session.add(report_details)
                db_session.flush()
            actual_report = self.get_existing_report_for_commit(commit)
            if actual_report is not None:
                # This case means the report exists in our system, it was just not saved
                #   yet into the new models therefore it needs backfilling
                self.save_full_report(commit, actual_report)
        elif current_report_row.details is None:
            log.warning(
                "Commit unexpectedly had CommitReport but no details",
                extra=dict(commit=commit.commitid, repoid=commit.repoid),
            )
            report_details = ReportDetails(
                report_id=current_report_row.id_, files_array=[]
            )
            db_session.add(report_details)
            db_session.flush()
        if not self.has_initialized_report(commit):
            report = self.create_new_report_for_commit(commit)
            if not report.is_empty():
                # This means there is a report to carryforward
                self.save_full_report(commit, report)
        return current_report_row

    def fetch_report_upload(
        self, commit_report: CommitReport, upload_id: int
    ) -> Optional[Upload]:
        db_session = commit_report.get_db_session()
        upload = db_session.query(Upload).filter_by(id_=int(upload_id)).first()
        if not upload:
            log.warning(
                f"Couldn't find existing Upload by id ({upload_id})",
                extra=dict(
                    commit=commit_report.commit_id,
                    repo=commit_report.commit.repoid,
                    upload_id=upload_id,
                ),
            )
        return upload

    def create_report_upload(
        self, normalized_arguments: Mapping[str, str], commit_report: CommitReport
    ) -> Upload:
        """Creates an `Upload` from the user-given arguments to a job

        The end goal here is that the `Upload` should have all the information needed to
            hypothetically redo the job later

        Args:
            normalized_arguments (Mapping[str, str]): The arguments as given by the user
            commit_report (CommitReport): The commit_report we will attach this `Uplaod` to

        Returns:
            Upload
        """
        db_session = commit_report.get_db_session()
        upload = Upload(
            external_id=normalized_arguments.get("reportid"),
            build_code=normalized_arguments.get("build"),
            build_url=normalized_arguments.get("build_url"),
            env=None,
            report_id=commit_report.id_,
            job_code=normalized_arguments.get("job"),
            name=normalized_arguments.get("name"),
            provider=normalized_arguments.get("service"),
            state="started",
            storage_path=normalized_arguments.get("url"),
            order_number=None,
            upload_extras={},
            upload_type=SessionType.uploaded.value,
            state_id=UploadState.uploaded.value,
            upload_type_id=UploadType.uploaded.value,
        )
        db_session.add(upload)
        db_session.flush()
        flags = normalized_arguments.get("flags")
        flags = flags.split(",") if flags else []
        self._attach_flags_to_upload(upload, flags)
        db_session.flush()
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
        for individual_flag in flag_names:
            existing_flag = (
                db_session.query(RepositoryFlag)
                .filter_by(repository_id=repoid, flag_name=individual_flag)
                .first()
            )
            if not existing_flag:
                existing_flag = RepositoryFlag(
                    repository_id=repoid, flag_name=individual_flag
                )
                db_session.add(existing_flag)
                db_session.flush()
            upload.flags.append(existing_flag)
            db_session.flush()
            all_flags.append(existing_flag)
        return all_flags

    def build_report(
        self, chunks, files, sessions, totals, report_class=None
    ) -> Report:
        if report_class is None:
            report_class = Report
            for sess in sessions.values():
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
        return self._do_build_report_from_commit(commit)

    def get_existing_report_for_commit(
        self, commit, report_class=None
    ) -> Optional[Report]:
        commitid = commit.commitid
        if commit.report_json is None:
            return None
        try:
            archive_service = self.get_archive_service(commit.repository)
            chunks = archive_service.read_chunks(commitid)
        except FileNotInStorageError:
            log.warning(
                "File for chunks not found in storage",
                extra=dict(commit=commitid, repo=commit.repoid),
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

    def _do_build_report_from_commit(self, commit) -> Report:
        report = self.get_existing_report_for_commit(commit)
        if report is not None:
            return report
        return self.create_new_report_for_commit(commit)

    @metrics.timer(
        f"services.report.ReportService.get_appropriate_commit_to_carryforward_from"
    )
    def get_appropriate_commit_to_carryforward_from(
        self, commit: Commit
    ) -> Optional[Commit]:
        parent_commit = commit.get_parent_commit()
        max_parenthood_deepness = 10
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

    @metrics.timer(f"services.report.ReportService.create_new_report_for_commit")
    def create_new_report_for_commit(self, commit: Commit) -> Report:
        log.info(
            "Creating new report for commit",
            extra=dict(commit=commit.commitid, repoid=commit.repoid),
        )
        if not self.current_yaml:
            return Report()
        if not self.current_yaml.has_any_carryforward():
            return Report()
        parent_commit = self.get_appropriate_commit_to_carryforward_from(commit)
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
        flags_to_carryforward = []
        report_flags = parent_report.get_flag_names()
        for flag_name in report_flags:
            if self.current_yaml.flag_has_carryfoward(flag_name):
                flags_to_carryforward.append(flag_name)
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
        return generate_carryforward_report(
            parent_report,
            flags_to_carryforward,
            paths_to_carryforward,
            session_extras=dict(carriedforward_from=parent_commit.commitid),
        )

    def build_report_from_raw_content(
        self, master: Optional[Report], upload: Upload
    ) -> ProcessingResult:
        """
            Processes an upload on top of an existing report `master` and returns
                a result, which could be succesful or not

            Note that this function does not modify the `upload` object, as this should
                be done by a separate function

        Args:
            master (Optional[Report]): The current report we are building on top of
            reports (ParsedRawReport): The uploaded report string fetched and parsed
            upload (Upload): The upload made by the user that we are processing
        """
        commit = upload.report.commit
        flags = upload.flag_names
        service = upload.provider
        build_url = upload.build_url
        build = upload.build_code
        job = upload.job_code
        name = upload.name
        url = upload.storage_path
        reportid = upload.external_id

        archive_url = url
        session = Session(
            provider=service,
            build=build,
            job=job,
            name=name,
            time=int(time()),
            flags=flags,
            archive=archive_url or url,
            url=build_url,
        )
        archive_service = self.get_archive_service(commit.repository)
        archive_url = upload.storage_path
        try:
            raw_uploaded_report = RawReportParser.parse_raw_report_from_bytes(
                archive_service.read_file(archive_url)
            )
        except FileNotInStorageError:
            return ProcessingResult(
                report=None,
                session=session,
                error=ProcessingError(
                    code="file_not_in_storage",
                    params={"location": archive_url},
                    is_retryable=True,
                ),
            )
        log.debug("Retrieved report for processing from url %s", archive_url)
        try:
            with metrics.timer(f"{self.metrics_prefix}.process_report") as t:
                report = process_raw_upload(
                    self.current_yaml, master, raw_uploaded_report, flags, session
                )
            log.info(
                "Successfully processed report",
                extra=dict(
                    session=session.id,
                    ci=f"{session.provider}:{session.build}:{session.job}",
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    reportid=reportid,
                    commit_yaml=self.current_yaml.to_dict(),
                    timing_ms=t.ms,
                    content_len=raw_uploaded_report.size,
                ),
            )
            return ProcessingResult(report=report, session=session, error=None)
        except ReportExpiredException:
            log.info(
                "Report %s is expired",
                reportid,
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            return ProcessingResult(
                report=None,
                session=session,
                error=ProcessingError(code="report_expired", params={}),
            )
        except ReportEmptyError:
            log.info(
                "Report %s is empty",
                reportid,
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            return ProcessingResult(
                report=None,
                session=session,
                error=ProcessingError(code="report_empty", params={}),
            )

    def update_upload_with_processing_result(
        self, upload_obj: Upload, processing_result: ProcessingResult
    ):
        db_session = upload_obj.get_db_session()
        session = processing_result.session
        if processing_result.error is None:
            upload_obj.state = "processed"
            upload_obj.state_id = UploadState.processed.value
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
                upload_totals.update_from_totals(session.totals)
        else:
            error = processing_result.error
            upload_obj.state = "error"
            upload_obj.state_id = UploadState.error.value
            error_obj = UploadError(
                upload_id=upload_obj.id,
                error_code=error.code,
                error_params=error.params,
            )
            db_session.add(error_obj)
            db_session.flush()

    def save_report(self, commit: Commit, report: Report):
        if len(report._chunks) > 2 * len(report._files) and len(report._files) > 0:
            report.repack()
        archive_service = self.get_archive_service(commit.repository)
        db_session = commit.get_db_session()
        totals, network_json_str = report.to_database()
        network = loads(network_json_str)
        archive_data = report.to_archive().encode()
        url = archive_service.write_chunks(commit.commitid, archive_data)
        commit.state = "complete" if report else "error"
        commit.totals = totals
        if (
            commit.totals is not None
            and "c" in commit.totals
            and commit.totals["c"] is None
        ):
            # temporary measure until we ensure the API and frontend don't expect not-null coverages
            commit.totals["c"] = 0
        commit.report_json = network
        files_array = [
            {
                "filename": k,
                "file_index": v.file_index,
                "file_totals": v.file_totals,
                "session_totals": v.session_totals,
                "diff_totals": v.diff_totals,
            }
            for k, v in report._files.items()
        ]
        if commit.report:
            commit.report.details.files_array = files_array
            report_totals = commit.report.totals
            if report_totals is None:
                report_totals = ReportLevelTotals(report_id=commit.report.id)
                db_session.add(report_totals)
            report_totals.update_from_totals(report.totals)
            db_session.flush()
        log.info(
            "Archived report",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
                url=url,
                number_sessions=len(network.get("sessions")),
                new_report_sessions=dict(
                    itertools.islice(network.get("sessions").items(), 20)
                ),
            ),
        )
        return {"url": url}

    def save_full_report(self, commit: Commit, report: Report):
        """
            Saves the report (into database and storage) AND takes care of backfilling its sessions
                like they were never in the database (useful for backfilling and carryforward cases)

        Args:
            commit (Commit): The commit we want to save the report to
            report (Report): The current report

        Returns:
            TYPE: Description
        """
        res = self.save_report(commit, report)
        db_session = commit.get_db_session()
        for sess_id, session in report.sessions.items():
            upload = Upload(
                build_code=session.build,
                build_url=session.url,
                env=session.env,
                external_id=uuid.uuid4(),
                job_code=session.job,
                name=session.name,
                order_number=sess_id,
                provider=session.provider,
                report_id=commit.report.id_,
                state="complete",
                storage_path=session.archive if session.archive is not None else "",
                upload_extras=session.session_extras or {},
                upload_type=session.session_type.value
                if session.session_type is not None
                else "unknown",
            )
            db_session.add(upload)
            db_session.flush()
            self._attach_flags_to_upload(upload, session.flags if session.flags else [])
            if session.totals is not None:
                upload_totals = UploadLevelTotals(upload_id=upload.id_)
                db_session.add(upload_totals)
                upload_totals.update_from_totals(session.totals)
        return res
