import typing
from io import BytesIO

import orjson
import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class GapProcessor(BaseLanguageProcessor):
    def matches_content(self, content: typing.Any, first_line: str, name: str) -> bool:
        try:
            val = content if isinstance(content, dict) else orjson.loads(first_line)
            return "Type" in val and "File" in val
        except (TypeError, ValueError):
            return False

    @sentry_sdk.trace
    def process(
        self,
        content: typing.Any,
        report_builder_session: ReportBuilderSession,
    ) -> None:
        if isinstance(content, dict):
            content = orjson.dumps(content)
        if isinstance(content, str):
            content = content.encode()
        return from_string(content, report_builder_session)


def from_string(string: bytes, report_builder_session: ReportBuilderSession) -> None:
    _file = None
    for encoded_line in BytesIO(string):
        line_str = encoded_line.decode(errors="replace").rstrip("\n")
        if not line_str:
            continue

        line = orjson.loads(line_str)
        if line["Type"] == "S":
            if _file is not None:
                report_builder_session.append(_file)

            _file = report_builder_session.create_coverage_file(line["File"])

        elif _file is not None:
            coverage = 0 if line["Type"] == "R" else 1
            _file.append(
                line["Line"],
                report_builder_session.create_coverage_line(
                    coverage,
                ),
            )

    # append last file
    if _file is not None:
        report_builder_session.append(_file)
