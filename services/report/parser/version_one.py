import base64
import logging
import zlib

import orjson
import sentry_sdk

from services.report.parser.types import (
    ParsedUploadedReportFile,
    VersionOneParsedRawReport,
)

log = logging.getLogger(__name__)


class VersionOneReportParser(object):
    @sentry_sdk.trace
    def parse_raw_report_from_bytes(
        self, raw_report: bytes
    ) -> VersionOneParsedRawReport:
        data = orjson.loads(raw_report)
        # want backwards compatibility with older versions of the CLI that still name this section path_fixes
        report_fixes = (
            data["report_fixes"] if "report_fixes" in data else data["path_fixes"]
        )
        return VersionOneParsedRawReport(
            toc=data["network_files"],
            uploaded_files=[
                _parse_single_coverage_file(x) for x in data["coverage_files"]
            ],
            report_fixes=report_fixes["value"],
        )


def _parse_single_coverage_file(coverage_file: dict) -> ParsedUploadedReportFile:
    actual_data = _parse_coverage_file_contents(coverage_file)
    return ParsedUploadedReportFile(
        filename=coverage_file["filename"],
        file_contents=actual_data,
        labels=coverage_file["labels"],
    )


def _parse_coverage_file_contents(coverage_file: dict) -> bytes:
    if coverage_file["format"] == "base64+compressed":
        return zlib.decompress(base64.b64decode(coverage_file["data"]))
    log.warning(
        "Unkown format found while parsing upload",
        extra=dict(coverage_file_filename=coverage_file["filename"]),
    )
    return coverage_file["data"]
