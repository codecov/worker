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
from services.path_fixer.fixpaths import clean_toc
from services.report.fixes import get_fixes_from_raw
from services.report.parser.types import ParsedUploadedReportFile
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
    __slots__ = ("report", "fully_deleted_sessions", "partially_deleted_sessions")
    report: Report
    fully_deleted_sessions: typing.List[int]
    partially_deleted_sessions: typing.List[int]


def process_raw_upload(
    commit_yaml, original_report, reports: ParsedUploadedReportFile, flags, session=None
) -> UploadProcessingResult:
    toc, env = None, None

    # ----------------------
    # Extract `git ls-files`
    # ----------------------
    if reports.has_toc():
        toc = reports.toc.read().decode(errors="replace").strip()
        toc = clean_toc(toc)
    if reports.has_env():
        env = reports.env.read().decode(errors="replace")

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
        ignored_file_lines = get_fixes_from_raw(
            reports.path_fixes.read().decode(errors="replace"), path_fixer
        )
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
    for report_file in reports.uploaded_files:
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
    for report_file in reports.uploaded_files:
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
    original_report.merge(temporary_report, joined=joined)
    session.totals = temporary_report.totals
    return UploadProcessingResult(
        report=original_report,
        partially_deleted_sessions=[],
        fully_deleted_sessions=[],
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
