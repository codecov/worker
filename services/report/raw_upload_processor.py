# -*- coding: utf-8 -*-

import logging
import random


from covreports.utils.sessions import Session
from covreports.reports.resources import Report

from helpers.exceptions import ReportEmptyError
from services.report.fixes import get_fixes_from_raw
from services.path_fixer.fixpaths import clean_toc
from services.path_fixer import PathFixer
from services.report.report_processor import process_report
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


def invert_pattern(string):
    if string.startswith('!'):
        return string[1:]
    else:
        return '!%s' % string


def process_raw_upload(commit_yaml, original_report, reports, flags, session=None):
    toc, env = None, None

    # ----------------------
    # Extract `git ls-files`
    # ----------------------
    _network = reports.find('<<<<<< network\n')
    if _network > -1:
        toc = reports[:_network].strip()
        reports = reports[_network+15:].strip()

    # --------------------
    # Extract env from toc
    # --------------------
    if toc:
        if '<<<<<< ENV\n' in toc:
            env, toc = tuple(toc.split('<<<<<< ENV\n', 1))

        toc = clean_toc(toc)

    # --------------------
    # Create Master Report
    # --------------------
    if not original_report:
        original_report = Report()

    path_fixer = PathFixer.init_from_user_yaml(
        commit_yaml=commit_yaml, toc=toc, flags=flags, base_path=None
    )

    # ------------------
    # Extract bash fixes
    # ------------------
    _fl = reports.find('\n# path=fixes\n')
    if _fl > -1:
        ignored_file_lines = get_fixes_from_raw(reports[_fl+14:], path_fixer)
        reports = reports[:_fl]
    else:
        ignored_file_lines = None

    # Get a sesisonid to merge into
    # anything merged into the original_report
    # will take on this sessionid
    sessionid, session = original_report.add_session(session or Session())
    session.id = sessionid
    if env:
        session.env = dict([e.split('=', 1) for e in env.split('\n') if '=' in e])

    if flags:
        session.flags = flags

    skip_files = set()

    # [javascript] check for both coverage.json and coverage/coverage.lcov
    if '# path=coverage/coverage.lcov' in reports and '# path=coverage/coverage.json' in reports:
        skip_files.add('coverage/coverage.lcov')

    # ---------------
    # Process reports
    # ---------------
    for report in reports.split('<<<<<< EOF'):
        report = report.strip()
        if report:
            if report.startswith('# path=') and report.split('\n', 1)[0].split('# path=')[1] in skip_files:
                log.info('Skipping file %s', report.split('\n', 1)[0].split('# path=')[1])
                continue

            report = process_report(
                report=report,
                commit_yaml=commit_yaml,
                sessionid=sessionid,
                ignored_lines=ignored_file_lines or {},
                path_fixer=path_fixer
            )

            if report:
                session.totals = report.totals

                # skip joining if flags express this fact
                joined = True
                for flag in (flags or []):
                    if read_yaml_field(commit_yaml, ('flags', flag, 'joined')) is False:
                        joined = False
                        break

                # merge the new report into maaster
                original_report.merge(report, joined=joined)

    # exit if empty
    if original_report.is_empty():
        raise ReportEmptyError('No files found in report.')

    if path_fixer.calculated_paths.get(None):
        ignored_files = sorted(path_fixer.calculated_paths.pop(None))
        log.info(
            "Some files were ignored",
            extra=dict(
                number=len(ignored_files),
                paths=random.sample(ignored_files, min(100, len(ignored_files))),
                session=sessionid
            )
        )

    path_with_same_results = [
        (key, len(value), list(value)[:10]) for key, value in path_fixer.calculated_paths.items() if len(value) >= 2
    ]
    if path_with_same_results:
        log.info(
            "Two different files went to the same result",
            extra=dict(
                number_of_paths=len(path_with_same_results),
                paths=path_with_same_results[:50],
                session=sessionid
            )
        )

    return original_report
