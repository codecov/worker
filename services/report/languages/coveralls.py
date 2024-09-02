import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class CoverallsProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return "source_files" in content

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def from_json(report: dict, report_builder_session: ReportBuilderSession) -> Report:
    # https://github.com/codecov/support/issues/253
    path_fixer, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
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
