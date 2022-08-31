import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class CoverallsProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return detect(content)

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        return from_json(content, path_fixer, ignored_lines, sessionid)


def detect(report):
    return "source_files" in report


def from_json(report, fix, ignored_lines, sessionid):
    # https://github.com/codecov/support/issues/253
    _report = Report()
    for _file in report["source_files"]:
        filename = fix(_file["name"])
        if filename:
            report_file = ReportFile(filename, ignore=ignored_lines.get(filename))
            for ln, coverage in enumerate(_file["coverage"], start=1):
                if coverage is not None:
                    report_file[ln] = ReportLine.create(
                        coverage, None, [[sessionid, coverage]]
                    )
            _report.append(report_file)

    return _report
