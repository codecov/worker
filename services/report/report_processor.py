# -*- coding: utf-8 -*-

from json import loads
from lxml import etree
import logging

from covreports.helpers.yaml import walk
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
    if raw_report.find('<plist version="1.0">') >= 0 or name.endswith('.plist'):
        return raw_report, 'plist'
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
            XCodeProcessor()
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
            try:
                return processor.process(
                    name, report, path_fixer, ignored_lines, sessionid, commit_yaml
                )
            except Exception:
                log.exception(
                    "There was an issue processing the specific file",
                    extra=dict(
                        processor_class=processor.get_processor_name(),
                        report_given_filename=name,
                        ignored_lines=ignored_lines,
                        sessionid=sessionid,
                        commit_yaml=commit_yaml,
                        first_line=first_line,
                        report_type=report_type
                    )
                )
                return None
    log.info(
        "File format could not be recognized",
        extra=dict(
            report_filename=name,
            first_line=first_line,
            report_type=report_type
        )
    )
    return None
