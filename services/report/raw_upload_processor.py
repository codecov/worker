# -*- coding: utf-8 -*-

import logging
import random
import typing
from dataclasses import dataclass

from shared.reports.resources import Report
from shared.utils.sessions import Session, SessionType

from helpers.exceptions import ReportEmptyError
from helpers.labels import get_all_report_labels, get_labels_per_session
from services.path_fixer import PathFixer
from services.report.fixes import get_fixes_from_raw
from services.report.parser.types import ParsedRawReport
from services.report.report_builder import ReportBuilder, SpecialLabelsEnum
from services.report.report_processor import process_report
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)

GLOBAL_LEVEL_LABEL = (
    SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label
)


def invert_pattern(string: str) -> str:
    if string.startswith("!"):
        return string[1:]
    else:
        return "!%s" % string


@dataclass
class UploadProcessingResult(object):
    __slots__ = (
        "report",
        "fully_deleted_sessions",
        "partially_deleted_sessions",
        "raw_report",
    )
    report: Report
    fully_deleted_sessions: typing.List[int]
    partially_deleted_sessions: typing.List[int]
    raw_report: ParsedRawReport


def process_raw_upload(
    commit_yaml, original_report, reports: ParsedRawReport, flags, session=None
) -> UploadProcessingResult:
    toc, env = None, None

    # ----------------------
    # Extract `git ls-files`
    # ----------------------
    if reports.has_toc():
        toc = reports.get_toc()
    if reports.has_env():
        env = reports.get_env()

    # --------------------
    # Create Master Report
    # --------------------
    if not original_report:
        original_report = Report()

    path_fixer = PathFixer.init_from_user_yaml(
        commit_yaml=commit_yaml, toc=toc, flags=flags
    )

    # ------------------
    # Extract bash fixes
    # ------------------
    if reports.has_path_fixes():
        ignored_file_lines = reports.get_path_fixes(path_fixer)
    else:
        ignored_file_lines = None

    # Get a sesisonid to merge into
    # anything merged into the original_report
    # will take on this sessionid
    sessionid, session = original_report.add_session(session or Session())
    session.id = sessionid
    if env:
        session.env = dict([e.split("=", 1) for e in env.split("\n") if "=" in e])

    if flags:
        session.flags = flags

    skip_files = set()

    # [javascript] check for both coverage.json and coverage/coverage.lcov
    for report_file in reports.get_uploaded_files():
        if report_file.filename == "coverage/coverage.json":
            skip_files.add("coverage/coverage.lcov")
    temporary_report = Report()
    joined = True
    for flag in flags or []:
        if read_yaml_field(commit_yaml, ("flags", flag, "joined")) is False:
            log.info(
                "Customer is using joined=False feature", extra=dict(flag_used=flag)
            )
            joined = False
    # ---------------
    # Process reports
    # ---------------
    ignored_lines = ignored_file_lines or {}
    for report_file in reports.get_uploaded_files():
        current_filename = report_file.filename
        if report_file.contents:
            if current_filename in skip_files:
                log.info("Skipping file %s", current_filename)
                continue
            path_fixer_to_use = path_fixer.get_relative_path_aware_pathfixer(
                current_filename
            )
            report_builder_to_use = ReportBuilder(
                commit_yaml, sessionid, ignored_lines, path_fixer_to_use
            )
            report = process_report(
                report=report_file, report_builder=report_builder_to_use
            )
            if report:
                temporary_report.merge(report, joined=True)
            path_fixer_to_use.log_abnormalities()
    _possibly_log_pathfixer_unusual_results(path_fixer, sessionid)
    if not temporary_report:
        raise ReportEmptyError("No files found in report.")
    session_manipulation_result = _adjust_sessions(
        original_report, temporary_report, session, commit_yaml
    )
    original_report.merge(temporary_report, joined=joined)
    session.totals = temporary_report.totals
    return UploadProcessingResult(
        report=original_report,
        fully_deleted_sessions=session_manipulation_result.fully_deleted_sessions,
        partially_deleted_sessions=session_manipulation_result.partially_deleted_sessions,
        raw_report=reports,
    )


@dataclass
class SessionAdjustmentResult(object):
    fully_deleted_sessions: set
    partially_deleted_sessions: set


def _adjust_sessions(original_report, to_merge_report, to_merge_session, current_yaml):
    session_ids_to_fully_delete = []
    session_ids_to_partially_delete = []
    to_merge_flags = to_merge_session.flags or []
    flags_under_carryforward_rules = [
        f for f in to_merge_flags if current_yaml.flag_has_carryfoward(f)
    ]
    to_partially_overwrite_flags = [
        f
        for f in flags_under_carryforward_rules
        if current_yaml.get_flag_configuration(f).get("carryforward_mode") == "labels"
    ]
    to_fully_overwrite_flags = [
        f
        for f in flags_under_carryforward_rules
        if f not in to_partially_overwrite_flags
    ]
    if to_fully_overwrite_flags or to_partially_overwrite_flags:
        for sess_id, curr_sess in original_report.sessions.items():
            if curr_sess.session_type == SessionType.carriedforward:
                if curr_sess.flags:
                    if any(f in to_fully_overwrite_flags for f in curr_sess.flags):
                        session_ids_to_fully_delete.append(sess_id)
                    if any(f in to_partially_overwrite_flags for f in curr_sess.flags):
                        session_ids_to_partially_delete.append(sess_id)
    actually_fully_deleted_sessions = set()
    if session_ids_to_fully_delete:
        log.info(
            "Deleted multiple sessions due to carriedforward overwrite",
            extra=dict(deleted_sessions=session_ids_to_fully_delete),
        )
        original_report.delete_multiple_sessions(session_ids_to_fully_delete)
        actually_fully_deleted_sessions.update(session_ids_to_fully_delete)
    if session_ids_to_partially_delete:
        log.info(
            "Partially deleting sessions due to label carryforward overwrite",
            extra=dict(deleted_sessions=session_ids_to_partially_delete),
        )
        all_labels = get_all_report_labels(to_merge_report)
        original_report.delete_labels(session_ids_to_partially_delete, all_labels)
        for s in session_ids_to_partially_delete:
            labels_now = get_labels_per_session(original_report, s)
            if not labels_now:
                log.info("Session has now no new labels, deleting whole session")
                actually_fully_deleted_sessions.add(s)
                original_report.delete_session(s)
    return SessionAdjustmentResult(
        sorted(actually_fully_deleted_sessions),
        sorted(set(session_ids_to_partially_delete) - actually_fully_deleted_sessions),
    )


def _possibly_log_pathfixer_unusual_results(path_fixer, sessionid):
    if path_fixer.calculated_paths.get(None):
        ignored_files = sorted(path_fixer.calculated_paths.pop(None))
        log.info(
            "Some files were ignored",
            extra=dict(
                number=len(ignored_files),
                paths=random.sample(ignored_files, min(100, len(ignored_files))),
                session=sessionid,
            ),
        )
    path_with_same_results = [
        (key, len(value), list(value)[:10])
        for key, value in path_fixer.calculated_paths.items()
        if len(value) >= 2
    ]
    if path_with_same_results:
        log.info(
            "Two different files went to the same result",
            extra=dict(
                number_of_paths=len(path_with_same_results),
                paths=path_with_same_results[:50],
                session=sessionid,
            ),
        )
