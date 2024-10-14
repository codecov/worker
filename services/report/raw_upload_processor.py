import logging
from dataclasses import dataclass

import sentry_sdk
from shared.reports.resources import Report
from shared.utils.sessions import Session, SessionType
from shared.yaml import UserYaml

from database.models.reports import Upload
from helpers.exceptions import ReportEmptyError, ReportExpiredException
from services.path_fixer import PathFixer
from services.report.parser.types import ParsedRawReport
from services.report.report_builder import ReportBuilder
from services.report.report_processor import process_report
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


@dataclass
class SessionAdjustmentResult:
    fully_deleted_sessions: list[int]
    partially_deleted_sessions: list[int]


@dataclass
class UploadProcessingResult:
    report: Report  # NOTE: this is just returning the input argument, and primarily used in tests
    session_adjustment: SessionAdjustmentResult


@sentry_sdk.trace
def process_raw_upload(
    commit_yaml,
    report: Report,
    raw_reports: ParsedRawReport,
    flags,
    session: Session,
    upload: Upload | None = None,
) -> UploadProcessingResult:
    toc, env = None, None

    # ----------------------
    # Extract `git ls-files`
    # ----------------------
    if raw_reports.has_toc():
        toc = raw_reports.get_toc()
    if raw_reports.has_env():
        env = raw_reports.get_env()

    path_fixer = PathFixer.init_from_user_yaml(
        commit_yaml=commit_yaml, toc=toc, flags=flags
    )

    # ------------------
    # Extract bash fixes
    # ------------------
    if raw_reports.has_report_fixes():
        ignored_file_lines = raw_reports.get_report_fixes(path_fixer)
    else:
        ignored_file_lines = None

    if env:
        session.env = dict([e.split("=", 1) for e in env.split("\n") if "=" in e])

    if flags:
        session.flags = flags

    sessionid = report.next_session_number()
    session.id = sessionid

    # [javascript] check for both coverage.json and coverage/coverage.lcov
    skip_files = set()
    for report_file in raw_reports.get_uploaded_files():
        if report_file.filename == "coverage/coverage.json":
            skip_files.add("coverage/coverage.lcov")

    temporary_report = Report()

    joined = True
    for flag in flags or []:
        if read_yaml_field(commit_yaml, ("flags", flag, "joined")) is False:
            log.info(
                "Customer is using joined=False feature", extra=dict(flag_used=flag)
            )
            joined = False  # TODO: ensure this works for parallel

    # ---------------
    # Process reports
    # ---------------
    ignored_lines = ignored_file_lines or {}
    for report_file in raw_reports.get_uploaded_files():
        current_filename = report_file.filename
        if current_filename in skip_files or not report_file.contents:
            continue

        path_fixer_to_use = path_fixer.get_relative_path_aware_pathfixer(
            current_filename
        )
        report_builder_to_use = ReportBuilder(
            commit_yaml,
            sessionid,
            ignored_lines,
            path_fixer_to_use,
        )
        try:
            report_from_file = process_report(
                report=report_file, report_builder=report_builder_to_use
            )
        except ReportExpiredException as r:
            r.filename = current_filename
            raise

        if report_from_file:
            temporary_report.merge(report_from_file, joined=True)

    if not temporary_report:
        raise ReportEmptyError("No files found in report.")

    # Now we actually add the session to the original_report
    # Because we know that the processing was successful
    _sessionid, session = report.add_session(session, use_id_from_session=True)
    # Adjust sessions removed carryforward sessions that are being replaced
    if session.flags:
        session_adjustment = clear_carryforward_sessions(
            report, session.flags, commit_yaml
        )
    else:
        session_adjustment = SessionAdjustmentResult([], [])

    report.merge(temporary_report, joined=joined)
    session.totals = temporary_report.totals

    return UploadProcessingResult(report=report, session_adjustment=session_adjustment)


@sentry_sdk.trace
def clear_carryforward_sessions(
    original_report: Report,
    to_merge_flags: list[str],
    current_yaml: UserYaml,
) -> SessionAdjustmentResult:
    to_fully_overwrite_flags = {
        f for f in to_merge_flags if current_yaml.flag_has_carryfoward(f)
    }

    session_ids_to_fully_delete = []
    if to_fully_overwrite_flags:
        for session_id, session in original_report.sessions.items():
            if session.session_type == SessionType.carriedforward and session.flags:
                if any(f in to_fully_overwrite_flags for f in session.flags):
                    session_ids_to_fully_delete.append(session_id)

    if session_ids_to_fully_delete:
        original_report.delete_multiple_sessions(session_ids_to_fully_delete)

    return SessionAdjustmentResult(sorted(session_ids_to_fully_delete), [])
