# -*- coding: utf-8 -*-

import logging
import numbers
from json import load
from typing import Any, Dict, List, Optional, Tuple

import sentry_sdk
from lxml import etree
from shared.metrics import Counter, Histogram
from shared.reports.resources import Report

from helpers.exceptions import CorruptRawReportError
from helpers.metrics import KiB, MiB
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


RAW_REPORT_PROCESSOR_RUNTIME_SECONDS = Histogram(
    "worker_services_report_raw_processor_duration_seconds",
    "Time it takes (in seconds) for a raw report processor to run",
    ["processor"],
    buckets=[0.05, 0.1, 0.5, 1, 2, 5, 7.5, 10, 15, 20, 30, 60, 120, 180, 300, 600, 900],
)

RAW_REPORT_SIZE = Histogram(
    "worker_services_report_raw_report_size",
    "Size (in bytes) of a raw report",
    ["processor"],
    buckets=[
        10 * KiB,
        100 * KiB,
        200 * KiB,
        500 * KiB,
        1 * MiB,
        2 * MiB,
        5 * MiB,
        10 * MiB,
        20 * MiB,
        50 * MiB,
        100 * MiB,
        200 * MiB,
    ],
)

RAW_REPORT_PROCESSOR_COUNTER = Counter(
    "worker_services_report_raw_processor_runs",
    "Number of times a raw report processor was run and with what result",
    ["processor", "result"],
)


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


def get_possible_processors_list(report_type: str) -> List[Any]:
    processor_dict: Dict[str, List[Any]] = {
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
    processors = get_possible_processors_list(report_type) if report_type else []
    for processor in processors:
        if processor.matches_content(parsed_report, first_line, name):
            sentry_sdk.metrics.incr(
                "services.report.report_processor.parser",
                tags={"type": type(processor).__name__},
            )
            RAW_REPORT_SIZE.labels(processor=processor.name).observe(report.size)
            with RAW_REPORT_PROCESSOR_RUNTIME_SECONDS.labels(
                processor=processor.name
            ).time():
                try:
                    res = processor.process(name, parsed_report, report_builder)
                    RAW_REPORT_PROCESSOR_COUNTER.labels(
                        processor=processor.name, result="success"
                    ).inc()
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
                    RAW_REPORT_PROCESSOR_COUNTER.labels(
                        processor=processor.name, result="corrupt_raw_report"
                    ).inc()
                    return None
                except Exception:
                    RAW_REPORT_PROCESSOR_COUNTER.labels(
                        processor=processor.name, result="failure"
                    ).inc()
                    raise
    log.warning(
        "File format could not be recognized",
        extra=dict(
            report_filename=name, first_line=first_line[:100], report_type=report_type
        ),
    )
    return None
