import typing
from io import BytesIO
from json import dumps, loads

import sentry_sdk
from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.path_fixer import PathFixer
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


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
        return from_string(
            content,
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
        )


def from_string(string: bytes, fix: PathFixer, ignored_lines: dict, sessionid: int):
    # https://github.com/codecov/support/issues/253
    report = Report()
    _file = None
    skip = True
    for encoded_line in BytesIO(string):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if line:
            line = loads(line)
            if line["Type"] == "S":
                if _file is not None:
                    report.append(_file)
                filename = fix(line["File"])
                if filename:
                    _file = ReportFile(filename, ignore=ignored_lines.get(filename))
                    skip = False
                else:
                    skip = True

            elif skip:
                continue

            else:
                coverage = 0 if line["Type"] == "R" else 1
                _file[line["Line"]] = ReportLine.create(
                    coverage, None, [[sessionid, coverage]]
                )

    # append last file
    report.append(_file)
    return report
