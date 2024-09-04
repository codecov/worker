import typing
from io import BytesIO
from json import dumps, loads

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    ReportBuilder,
    ReportBuilderSession,
)


class GapProcessor(BaseLanguageProcessor):
    def matches_content(self, content: typing.Any, first_line: str, name: str) -> bool:
        try:
            val = content if isinstance(content, dict) else loads(first_line)
            return "Type" in val and "File" in val
        except (TypeError, ValueError):
            return False

    @sentry_sdk.trace
    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        if isinstance(content, dict):
            content = dumps(content)
        if isinstance(content, str):
            content = content.encode()
        return from_string(content, report_builder.create_report_builder_session(name))


def from_string(string: bytes, report_builder_session: ReportBuilderSession):
    path_fixer, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )
    _file = None
    skip = True
    for encoded_line in BytesIO(string):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if not line:
            continue

        line = loads(line)
        if line["Type"] == "S":
            if _file is not None:
                report_builder_session.append(_file)
            filename = path_fixer(line["File"])
            if filename:
                _file = report_builder_session.file_class(
                    name=filename, ignore=ignored_lines.get(filename)
                )
                skip = False
            else:
                skip = True

        elif skip:
            continue

        else:
            coverage = 0 if line["Type"] == "R" else 1
            _file.append(
                line["Line"],
                report_builder_session.create_coverage_line(
                    coverage,
                ),
            )

    # append last file
    report_builder_session.append(_file)

    return report_builder_session.output_report()
