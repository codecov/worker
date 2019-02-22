# -*- coding: utf-8 -*-

import re

from pathmap import resolve_by_method

from covreports.helpers.yaml import walk
from covreports.utils.sessions import Session
from covreports.resources import Report

from services.report.fixes import get_fixes_from_raw
from services.report.match import patterns_to_func
from services.report.fixpaths import fixpaths_to_func, clean_toc, clean_path

from services.report.report_processor import process_report


def invert_pattern(string):
    if string.startswith('!'):
        return string[1:]
    else:
        return '!%s' % string


def process_raw_upload(repository, original_report, reports, flags, session=None):
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

    # -------------------
    # Make custom_fixes()
    # -------------------
    custom_fixes = fixpaths_to_func(walk(repository.data['yaml'], ('fixes', )) or [])

    # -------------
    # Make ignore[]
    # -------------
    path_patterns = list(
        map(
            invert_pattern,
            walk(repository.data['yaml'], ('ignore', )) or []
        )
    )

    # flag ignore
    if flags:
        for flag in flags:
            path_patterns.extend(list(map(invert_pattern,
                                     walk(repository.data['yaml'],
                                          ('flags', flag, 'ignore')) or [])))

            path_patterns.extend(walk(repository.data['yaml'],
                                      ('flags', flag, 'paths')) or [])

    # callable custom ignore
    path_matcher = patterns_to_func(set(path_patterns))
    resolver = resolve_by_method(toc) if toc else None
    disable_default_path_fixes = walk(repository.data['yaml'], ('codecov', 'disable_default_path_fixes'))

    def path_fixer(p):
        return clean_path(custom_fixes, path_matcher, resolver, p,
                          disable_default_path_fixes=disable_default_path_fixes)

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
                repository.data['task'].log('info',
                                            'Skipping file.',
                                            filename=report.split('\n', 1)[0].split('# path=')[1])
                continue

            report = process_report(
                report=report,
                repository=repository,
                sessionid=sessionid,
                ignored_lines=ignored_file_lines or {},
                path_fixer=path_fixer
            )
            print(report)
            if report:
                session.totals = report.totals

                # skip joining if flags express this fact
                joined = True
                for flag in (flags or []):
                    if walk(repository.data['yaml'], ('flags', flag, 'joined')) is False:
                        joined = False
                        break

                # merge the new report into maaster
                original_report.merge(report, joined=joined)

    # exit if empty
    assert not original_report.is_empty(), 'No files found in report.'

    return original_report
