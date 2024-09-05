import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class CoverallsProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return "source_files" in content

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def from_json(report: dict, report_builder_session: ReportBuilderSession) -> Report:
    for file in report["source_files"]:
        _file = report_builder_session.create_coverage_file(file["name"])
        if _file is None:
            continue

        for ln, coverage in enumerate(file["coverage"], start=1):
            if coverage is not None:
                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(
                        coverage,
                    ),
                )
        report_builder_session.append(_file)

    return report_builder_session.output_report()
