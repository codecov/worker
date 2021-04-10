# -*- coding: utf-8 -*-

import logging
import random


from shared.utils.sessions import Session
from shared.reports.resources import Report

from helpers.exceptions import ReportEmptyError
from services.report.fixes import get_fixes_from_raw
from services.path_fixer.fixpaths import clean_toc
from services.path_fixer import PathFixer
from services.report.report_processor import process_report
from services.report.parser import ParsedUploadedReportFile
from services.yaml import read_yaml_field
from typing import Any

log = logging.getLogger(__name__)


def invert_pattern(string: str) -> str:
    if string.startswith("!"):
        return string[1:]
    else:
        return "!%s" % string


def process_raw_upload(
    commit_yaml, original_report, reports: ParsedUploadedReportFile, flags, session=None
) -> Any:
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
    for report_file in reports.uploaded_files:
        current_filename = report_file.filename
        if report_file.contents:
            if current_filename in skip_files:
                log.info("Skipping file %s", current_filename)
                continue
            path_fixer_to_use = path_fixer.get_relative_path_aware_pathfixer(
                current_filename
            )
            report = process_report(
                report=report_file,
                commit_yaml=commit_yaml,
                sessionid=sessionid,
                ignored_lines=ignored_file_lines or {},
                path_fixer=path_fixer_to_use,
            )
            if report:
                temporary_report.merge(report, joined=joined)
            path_fixer_to_use.log_abnormalities()
    if temporary_report:
        original_report.merge(temporary_report, joined=joined)
        session.totals = temporary_report.totals
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

    # exit if empty
    if original_report.is_empty():
        raise ReportEmptyError("No files found in report.")

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

    return original_report
