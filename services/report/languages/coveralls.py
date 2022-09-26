import typing

from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class CoverallsProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return detect(content)

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def detect(report):
    return "source_files" in report


def from_json(report, report_builder_session: ReportBuilderSession) -> Report:
    # https://github.com/codecov/support/issues/253
    path_fixer, ignored_lines, sessionid, repo_yaml = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.sessionid,
        report_builder_session.current_yaml,
    )
    for _file in report["source_files"]:
        filename = path_fixer(_file["name"])
        if filename:
            report_file = report_builder_session.file_class(
                filename, ignore=ignored_lines.get(filename)
            )
            for ln, coverage in enumerate(_file["coverage"], start=1):
                if coverage is not None:
                    report_file[ln] = report_builder_session.create_coverage_line(
                        filename=filename,
                        coverage=coverage,
                        coverage_type=CoverageType.line,
                    )
            report_builder_session.append(report_file)

    return report_builder_session.output_report()
