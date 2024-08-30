import json
import logging
from typing import Literal
from xml.etree.ElementTree import Element

import sentry_sdk
from lxml import etree
from shared.metrics import Counter, Histogram
from shared.reports.resources import Report

from helpers.exceptions import CorruptRawReportError
from helpers.metrics import KiB, MiB
from services.report.languages.base import BaseLanguageProcessor
from services.report.languages.helpers import remove_non_ascii
from services.report.parser.types import ParsedUploadedReportFile
from services.report.report_builder import ReportBuilder

from .languages.bullseye import BullseyeProcessor
from .languages.clover import CloverProcessor
from .languages.cobertura import CoberturaProcessor
from .languages.coveralls import CoverallsProcessor
from .languages.csharp import CSharpProcessor
from .languages.dlst import DLSTProcessor
from .languages.elm import ElmProcessor
from .languages.flowcover import FlowcoverProcessor
from .languages.gap import GapProcessor
from .languages.gcov import GcovProcessor
from .languages.go import GoProcessor
from .languages.jacoco import JacocoProcessor
from .languages.jetbrainsxml import JetBrainsXMLProcessor
from .languages.lcov import LcovProcessor
from .languages.lua import LuaProcessor
from .languages.mono import MonoProcessor
from .languages.node import NodeProcessor
from .languages.pycoverage import PyCoverageProcessor
from .languages.rlang import RlangProcessor
from .languages.salesforce import SalesforceProcessor
from .languages.scala import ScalaProcessor
from .languages.scoverage import SCoverageProcessor
from .languages.simplecov import SimplecovProcessor
from .languages.v1 import VOneProcessor
from .languages.vb import VbProcessor
from .languages.vb2 import VbTwoProcessor
from .languages.xcode import XCodeProcessor
from .languages.xcodeplist import XCodePlistProcessor

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


def report_type_matching(
    report: ParsedUploadedReportFile, first_line: str
) -> (
    tuple[bytes, Literal["txt"] | Literal["plist"]]
    | tuple[dict | list, Literal["json"]]
    | tuple[Element, Literal["xml"]]
):
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
    if not raw_report:
        return raw_report, "txt"
    try:
        processed = json.load(report.file_contents)
        if isinstance(processed, dict) or isinstance(processed, list):
            return processed, "json"
    except ValueError:
        pass
    try:
        parser = etree.XMLParser(recover=True, resolve_entities=False)
        processed = etree.fromstring(raw_report, parser=parser)
        if processed is not None and len(processed) > 0:
            return processed, "xml"
    except ValueError:
        pass
    return raw_report, "txt"


def process_report(
    report: ParsedUploadedReportFile, report_builder: ReportBuilder
) -> Report | None:
    report_filename = report.filename or ""
    first_line = remove_non_ascii(report.get_first_line().decode(errors="replace"))
    raw_report = report.contents

    if b"<classycle " in raw_report and b"</classycle>" in raw_report:
        log.warning(
            "Ignored <classycle> report",
            extra=dict(report_filename=report_filename, first_line=first_line[:100]),
        )
        return None

    parsed_report, report_type = report_type_matching(report, first_line)

    processors: list[BaseLanguageProcessor] = []
    if report_type == "plist":
        processors = [XCodePlistProcessor()]
    elif report_type == "xml":
        processors = [
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
        ]
    elif report_type == "txt":
        if parsed_report[-11:] == b"has no code":
            # empty [dlst]
            return None
        processors = [
            LcovProcessor(),
            GcovProcessor(),
            LuaProcessor(),
            GapProcessor(),
            DLSTProcessor(),
            GoProcessor(),
            XCodeProcessor(),
        ]
    elif report_type == "json":
        processors = [
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
        ]

    for processor in processors:
        if not processor.matches_content(parsed_report, first_line, report_filename):
            continue
        processor_name = type(processor).__name__

        sentry_sdk.metrics.incr(
            "services.report.report_processor.parser",
            tags={"type": processor_name},
        )
        RAW_REPORT_SIZE.labels(processor=processor_name).observe(report.size)
        with RAW_REPORT_PROCESSOR_RUNTIME_SECONDS.labels(
            processor=processor_name
        ).time():
            try:
                res = processor.process(report_filename, parsed_report, report_builder)
                RAW_REPORT_PROCESSOR_COUNTER.labels(
                    processor=processor_name, result="success"
                ).inc()
                return res
            except CorruptRawReportError as e:
                log.warning(
                    "Processor matched file but later a problem with file was discovered",
                    extra=dict(
                        processor_name=processor_name,
                        expected_format=e.expected_format,
                        corruption_error=e.corruption_error,
                    ),
                    exc_info=True,
                )
                RAW_REPORT_PROCESSOR_COUNTER.labels(
                    processor=processor_name, result="corrupt_raw_report"
                ).inc()
                return None
            except Exception:
                RAW_REPORT_PROCESSOR_COUNTER.labels(
                    processor=processor_name, result="failure"
                ).inc()
                raise
    log.warning(
        "File format could not be recognized",
        extra=dict(
            report_filename=report_filename,
            first_line=first_line[:100],
            report_type=report_type,
        ),
    )
    return None
