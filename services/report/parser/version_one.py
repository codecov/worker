import base64
import logging
import zlib
from io import BytesIO

import orjson
import sentry_sdk

from services.report.parser.types import (
    ParsedUploadedReportFile,
    VersionOneParsedRawReport,
)

log = logging.getLogger(__name__)


class VersionOneReportParser(object):
    @sentry_sdk.trace
    def parse_raw_report_from_bytes(self, raw_report: bytes):
        data = orjson.loads(raw_report)
        return VersionOneParsedRawReport(
            toc=data["network_files"],
            env=None,
            uploaded_files=[
                self._parse_single_coverage_file(x) for x in data["coverage_files"]
            ],
            report_fixes=self._parse_report_fixes(
                # want backwards compatibility with older versions of the CLI that still name this section path_fixes
                data["report_fixes"] if "report_fixes" in data else data["path_fixes"]
            ),
        )

    def _parse_report_fixes(self, value):
        return value["value"]

    def _parse_single_coverage_file(self, coverage_file):
        actual_data = self._parse_coverage_file_contents(coverage_file)
        return ParsedUploadedReportFile(
            filename=coverage_file["filename"],
            file_contents=actual_data,
            labels=coverage_file["labels"],
        )

    def _parse_coverage_file_contents(self, coverage_file):
        if coverage_file["format"] == "base64+compressed":
            return BytesIO(zlib.decompress(base64.b64decode(coverage_file["data"])))
        log.warning(
            "Unkown format found while parsing upload",
            extra=dict(coverage_file_filename=coverage_file["filename"]),
        )
        return coverage_file["data"]
