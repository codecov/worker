# -*- coding: utf-8 -*-

from json import loads
from lxml import etree
import logging

from services.report.languages.helpers import remove_non_ascii

from services.report.languages import (
    SCoverageProcessor, JetBrainsXMLProcessor, CloverProcessor,
    MonoProcessor, CSharpProcessor, JacocoProcessor, VbProcessor, VbTwoProcessor,
    CoberturaProcessor, SalesforceProcessor, ElmProcessor, RlangProcessor, FlowcoverProcessor,
    VOneProcessor, ScalaProcessor, CoverallsProcessor, RspecProcessor, NodeProcessor,
    LcovProcessor, GcovProcessor, LuaProcessor, GapProcessor, DLSTProcessor, GoProcessor,
    XCodeProcessor, XCodePlistProcessor
)

log = logging.getLogger(__name__)


def report_type_matching(name, raw_report):
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    first_line = raw_report.split('\n', 1)[0]
    xcode_first_line_endings = (
        '.h:', '.m:', '.swift:', '.hpp:', '.cpp:', '.cxx:',  '.c:', '.C:', '.cc:', '.cxx:', '.c++:'
    )
    xcode_filename_endings = ('app.coverage.txt', 'framework.coverage.txt', 'xctest.coverage.txt')
    if first_line.endswith(xcode_first_line_endings) or name.endswith(xcode_filename_endings):
        return raw_report, 'txt'
    if raw_report.find('<plist version="1.0">') >= 0 or name.endswith('.plist'):
        return raw_report, 'plist'
    if raw_report:
        try:
            processed = loads(raw_report)
            if processed != dict():
                return processed, 'json'
        except ValueError:
            pass
        if '<classycle ' in raw_report and '</classycle>' in raw_report:
            return None, None
        try:
            processed = etree.fromstring(raw_report, parser=parser)
        except ValueError:
            try:
                processed = etree.fromstring(raw_report.encode(), parser=parser)
            except ValueError:
                pass
        if processed is not None and len(processed) > 0:
            return processed, 'xml'
    return raw_report, 'txt'


def get_possible_processors_list(report_type):
    processor_dict = {
        'plist': [
            XCodePlistProcessor()
        ],
        'xml': [
            SCoverageProcessor(),
            JetBrainsXMLProcessor(),
            CloverProcessor(),
            MonoProcessor(),
            CSharpProcessor(),
            JacocoProcessor(),
            VbProcessor(),
            VbTwoProcessor(),
            CoberturaProcessor()
        ],
        'txt': [
            LcovProcessor(),
            GcovProcessor(),
            LuaProcessor(),
            GapProcessor(),
            DLSTProcessor(),
            GoProcessor(),
            XCodeProcessor(),
        ],
        'json': [
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
    }
    return processor_dict.get(report_type, [])


def process_report(report, commit_yaml, sessionid, ignored_lines, path_fixer):
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
    report, report_type = report_type_matching(name, report)
    if original_report[-11:] == 'has no code':
        # empty [dlst]
        return None
    processors = get_possible_processors_list(report_type)
    # [xcode]
    for processor in processors:
        if processor.matches_content(report, first_line, name):
            return processor.process(
                name, report, path_fixer, ignored_lines, sessionid, commit_yaml
            )
    log.info(
        "File format could not be recognized",
        extra=dict(
            report_filename=name,
            first_line=first_line,
            report_type=report_type
        )
    )
    return None
