# -*- coding: utf-8 -*-

import re
from json import loads
from lxml import etree
import logging

from covreports.helpers.yaml import walk
from services.report import languages
from services.report.languages.helpers import remove_non_ascii

from services.report.languages import (
    SCoverageProcessor, JetBrainsXMLProcessor, CloverProcessor,
    MonoProcessor, CSharpProcessor, JacocoProcessor, VbProcessor, VbTwoProcessor,
    CoberturaProcessor, SalesforceProcessor, ElmProcessor, RlangProcessor, FlowcoverProcessor,
    VOneProcessor, ScalaProcessor, CoverallsProcessor, RspecProcessor, NodeProcessor,
    LcovProcessor, GcovProcessor, LuaProcessor, GapProcessor, DLSTProcessor, GoProcessor,
    XCodeProcessor
)

log = logging.getLogger(__name__)


def report_type_matching(raw_report):
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    first_line = raw_report.split('\n', 1)[0]
    if raw_report and (
        (first_line and first_line[0] == '<' and len(first_line) > 1 and first_line[1] in 'csCrR') or
        raw_report[:5] == '<?xml'
    ):
        if '<classycle ' in raw_report and '</classycle>' in raw_report:
            return None, None
        try:
            processed = etree.fromstring(raw_report, parser=parser)
        except ValueError:
            processed = etree.fromstring(raw_report.encode(), parser=parser)
        if processed is not None and len(processed) > 0:
            return processed, 'xml'
    else:
        if first_line and first_line[0] in ['{', '['] and first_line != '{}':
            try:
                processed = loads(raw_report)
                return processed, 'json'
            except ValueError:
                pass
    return raw_report, 'txt'


def process_report(report, repository, sessionid, ignored_lines, path_fixer):
    name = ''
    if report[:7] == '# path=':
        if '\n' not in report:
            return None
        name, report = report[7:].split('\n', 1)
        report = report.strip()
        if not report:
            return None

        name = name.replace('#', '/').replace('\\', '/')

    first_line = remove_non_ascii(report.split('\n', 1)[0])
    original_report = report
    report, report_type = report_type_matching(report)

    # tag anything larger the 10 seconds
    if name.endswith('xccoverage.plist') or (not name and original_report.find('<plist version="1.0">') > -1 and report.startswith('<?xml')):
        # [xcode]
        return languages.xcodeplist.from_xml(report, path_fixer, ignored_lines, sessionid)

    elif original_report[-11:] == 'has no code':
        # empty [dlst]
        return None

    elif report_type == 'xml':
        if report is None or len(report) is 0:
            return
        xml_processors = [
            SCoverageProcessor(),
            JetBrainsXMLProcessor(),
            CloverProcessor(),
            MonoProcessor(),
            CSharpProcessor(),
            JacocoProcessor(),
            VbProcessor(),
            VbTwoProcessor(),
            CoberturaProcessor()
        ]
        for processor in xml_processors:
            if processor.matches_content(report, first_line, name):
                return processor.process(
                    name, report, path_fixer, ignored_lines, sessionid, repository.data['yaml']
                )
    elif report_type == 'txt':
        txt = [
            LcovProcessor(),
            GcovProcessor(),
            LuaProcessor(),
            GapProcessor(),
            DLSTProcessor(),
            GoProcessor(),
            XCodeProcessor()
        ]
        for processor in txt:
            if processor.matches_content(report, first_line, name):
                return processor.process(
                    name, report, path_fixer, ignored_lines, sessionid, repository.data['yaml']
                )

    elif report_type == 'json':

        json_processors = [
            SalesforceProcessor(),
            ElmProcessor(),
            RlangProcessor(),
            FlowcoverProcessor(),
            VOneProcessor(),
            ScalaProcessor(),
            CoverallsProcessor(),
            RspecProcessor(),
            GapProcessor(),
            NodeProcessor(),
        ]
        for processor in json_processors:
            if processor.matches_content(report, first_line, name):
                return processor.process(
                    name, report, path_fixer, ignored_lines, sessionid, repository.data['yaml']
                )

        # Just leaving those here out of explicitness, but at this point, no processor matched
        if walk(report, ('stats', 'suites')):
            # https://sentry.io/codecov/v4/issues/160367055/activity/
            return None

        elif 'conda.' in str(report.get('url')):
            # https://sentry.io/codecov/production/issues/661305768
            return None
