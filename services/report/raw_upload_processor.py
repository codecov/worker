import logging
from dataclasses import dataclass

import sentry_sdk
from shared.reports.resources import Report
from shared.utils.sessions import Session, SessionType
from shared.yaml import UserYaml

from database.models.reports import Upload
from helpers.exceptions import ReportEmptyError, ReportExpiredException
from helpers.labels import get_all_report_labels, get_labels_per_session
from services.path_fixer import PathFixer
from services.processing.metrics import LABELS_USAGE
from services.report.parser.types import ParsedRawReport
from services.report.report_builder import ReportBuilder
from services.report.report_processor import process_report
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


@dataclass
class SessionAdjustmentResult:
    fully_deleted_sessions: list[int]
    partially_deleted_sessions: list[int]


@sentry_sdk.trace
def process_raw_upload(
    commit_yaml,
    raw_reports: ParsedRawReport,
    flags: list[str],
    session: Session,
) -> Report:
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

    # [javascript] check for both coverage.json and coverage/coverage.lcov
    skip_files = set()
    for report_file in raw_reports.get_uploaded_files():
        if report_file.filename == "coverage/coverage.json":
            skip_files.add("coverage/coverage.lcov")

    report = Report()
    sessionid = session.id = report.next_session_number()

    # TODO(swatinem): make this work in parallel mode:
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
        if report_builder_to_use.supports_labels():
            # NOTE: this here is very conservative, as it checks for *any* `carryforward_mode=labels`,
            # not taking the `flags` into account at all.
            LABELS_USAGE.labels(codepath="report_builder").inc()
        try:
            report_from_file = process_report(
                report=report_file, report_builder=report_builder_to_use
            )
        except ReportExpiredException as r:
            r.filename = current_filename
            raise

        if not report_from_file:
            continue
        if report.is_empty():
            # if the initial report is empty, we can avoid a costly merge operation
            report = report_from_file
        else:
            # merging the smaller report into the larger one is faster,
            # so swap the two reports in that case.
            if len(report_from_file._files) > len(report._files):
                report_from_file, report = report, report_from_file

            report.merge(report_from_file, joined=True)

    if not report:
        raise ReportEmptyError("No files found in report.")

    _sessionid, session = report.add_session(session, use_id_from_session=True)
    session.totals = report.totals

    return report


@sentry_sdk.trace
def clear_carryforward_sessions(
    original_report: Report,
    to_merge_report: Report,
    to_merge_flags: list[str],
    current_yaml: UserYaml,
    upload: Upload | None = None,
):
    flags_under_carryforward_rules = {
        f for f in to_merge_flags if current_yaml.flag_has_carryfoward(f)
    }
    to_partially_overwrite_flags = {
        f
        for f in flags_under_carryforward_rules
        if current_yaml.get_flag_configuration(f).get("carryforward_mode") == "labels"
    }
    if to_partially_overwrite_flags:
        # NOTE: this here might be the most accurate counter, as it takes into account the
        # actual `to_merge_flags` that were used for this particular upload.
        LABELS_USAGE.labels(codepath="carryforward_cleanup").inc()

    to_fully_overwrite_flags = flags_under_carryforward_rules.difference(
        to_partially_overwrite_flags
    )

    if upload is None and to_partially_overwrite_flags:
        log.warning("Upload is None, but there are partial_overwrite_flags present")

    session_ids_to_fully_delete = []
    session_ids_to_partially_delete = []

    if to_fully_overwrite_flags or to_partially_overwrite_flags:
        for session_id, session in original_report.sessions.items():
            if session.session_type == SessionType.carriedforward and session.flags:
                if any(f in to_fully_overwrite_flags for f in session.flags):
                    session_ids_to_fully_delete.append(session_id)
                if any(f in to_partially_overwrite_flags for f in session.flags):
                    session_ids_to_partially_delete.append(session_id)

    actually_fully_deleted_sessions = set()
    if session_ids_to_fully_delete:
        original_report.delete_multiple_sessions(session_ids_to_fully_delete)
        actually_fully_deleted_sessions.update(session_ids_to_fully_delete)

    if session_ids_to_partially_delete:
        all_labels = get_all_report_labels(to_merge_report)
        original_report.delete_labels(session_ids_to_partially_delete, all_labels)
        for s in session_ids_to_partially_delete:
            labels_now = get_labels_per_session(original_report, s)
            if not labels_now:
                actually_fully_deleted_sessions.add(s)
                original_report.delete_session(s)

    return SessionAdjustmentResult(
        sorted(actually_fully_deleted_sessions),
        sorted(set(session_ids_to_partially_delete) - actually_fully_deleted_sessions),
    )
