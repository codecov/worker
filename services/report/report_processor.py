# -*- coding: utf-8 -*-

import logging
import numbers
from json import load
from typing import Any, Optional, Tuple

from lxml import etree
from shared.reports.resources import Report

from helpers.exceptions import CorruptRawReportError
from helpers.metrics import metrics
from services.report.languages import (
    BullseyeProcessor,
    CloverProcessor,
    CoberturaProcessor,
    CoverallsProcessor,
    CSharpProcessor,
    DLSTProcessor,
    ElmProcessor,
    FlowcoverProcessor,
    GapProcessor,
    GcovProcessor,
    GoProcessor,
    JacocoProcessor,
    JetBrainsXMLProcessor,
    LcovProcessor,
    LuaProcessor,
    MonoProcessor,
    NodeProcessor,
    PyCoverageProcessor,
    RlangProcessor,
    SalesforceProcessor,
    ScalaProcessor,
    SCoverageProcessor,
    SimplecovProcessor,
    VbProcessor,
    VbTwoProcessor,
    VOneProcessor,
    XCodePlistProcessor,
    XCodeProcessor,
)
from services.report.languages.helpers import remove_non_ascii
from services.report.parser.types import ParsedUploadedReportFile
from services.report.report_builder import ReportBuilder

log = logging.getLogger(__name__)


def report_type_matching(report: ParsedUploadedReportFile) -> Tuple[Any, Optional[str]]:
    first_line = remove_non_ascii(report.get_first_line().decode(errors="replace"))
    name = report.filename or ""
    raw_report = report.contents
    xcode_first_line_endings = (
        ".h:",
        ".m:",
        ".swift:",
        ".hpp:",
        ".cpp:",
        ".cxx:",
        ".c:",
        ".C:",
        ".cc:",
        ".cxx:",
        ".c++:",
    )
    xcode_filename_endings = (
        "app.coverage.txt",
        "framework.coverage.txt",
        "xctest.coverage.txt",
    )
    if first_line.endswith(xcode_first_line_endings) or name.endswith(
        xcode_filename_endings
    ):
        return raw_report, "txt"
    if raw_report.find(b'<plist version="1.0">') >= 0 or name.endswith(".plist"):
        return raw_report, "plist"
    if raw_report:
        try:
            processed = load(report.file_contents)
            if processed != dict() and not isinstance(processed, numbers.Number):
                return processed, "json"
        except ValueError:
            pass
        if b"<classycle " in raw_report and b"</classycle>" in raw_report:
            return None, None
        try:
            parser = etree.XMLParser(recover=True, resolve_entities=False)
            processed = etree.fromstring(raw_report, parser=parser)
            if processed is not None and len(processed) > 0:
                return processed, "xml"
        except ValueError:
            pass
    return raw_report, "txt"


def get_possible_processors_list(report_type) -> list:
    processor_dict = {
        "plist": [XCodePlistProcessor()],
        "xml": [
            BullseyeProcessor(),
            SCoverageProcessor(),
            JetBrainsXMLProcessor(),
            CloverProcessor(),
            MonoProcessor(),
            CSharpProcessor(),
            JacocoProcessor(),
            VbProcessor(),
            VbTwoProcessor(),
            CoberturaProcessor(),
        ],
        "txt": [
            LcovProcessor(),
            GcovProcessor(),
            LuaProcessor(),
            GapProcessor(),
            DLSTProcessor(),
            GoProcessor(),
            XCodeProcessor(),
        ],
        "json": [
            SalesforceProcessor(),
            ElmProcessor(),
            RlangProcessor(),
            FlowcoverProcessor(),
            VOneProcessor(),
            ScalaProcessor(),
            CoverallsProcessor(),
            SimplecovProcessor(),
            GapProcessor(),
            PyCoverageProcessor(),
            NodeProcessor(),
        ],
    }
    return processor_dict.get(report_type, [])


def process_report(
    report: ParsedUploadedReportFile, report_builder: ReportBuilder
) -> Optional[Report]:
    name = report.filename or ""
    first_line = remove_non_ascii(report.get_first_line().decode(errors="replace"))
    parsed_report, report_type = report_type_matching(report)
    if report_type == "txt" and parsed_report[-11:] == b"has no code":
        # empty [dlst]
        return None
    processors = get_possible_processors_list(report_type)
    for processor in processors:
        if processor.matches_content(parsed_report, first_line, name):
            with metrics.timer(
                f"worker.services.report.processors.{processor.name}.run"
            ):
                try:
                    res = processor.process(name, parsed_report, report_builder)
                    metrics.incr(
                        f"worker.services.report.processors.{processor.name}.success"
                    )
                    return res
                except CorruptRawReportError as e:
                    log.warning(
                        "Processor matched file but later a problem with file was discovered",
                        extra=dict(
                            processor_name=processor.name,
                            expected_format=e.expected_format,
                            corruption_error=e.corruption_error,
                        ),
                        exc_info=True,
                    )
                    return None
                except Exception:
                    metrics.incr(
                        f"worker.services.report.processors.{processor.name}.failure"
                    )
                    raise
    log.info(
        "File format could not be recognized",
        extra=dict(
            report_filename=name, first_line=first_line[:100], report_type=report_type
        ),
    )
    return None
