import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    ReportBuilder,
    ReportBuilderSession,
)


class ScalaProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return "fileReports" in content

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def from_json(data_dict: dict, report_builder_session: ReportBuilderSession) -> Report:
    ignored_lines = report_builder_session.ignored_lines
    for f in data_dict["fileReports"]:
        filename = report_builder_session.path_fixer(f["filename"])
        if filename is None:
            continue

        _file = report_builder_session.file_class(
            filename, ignore=ignored_lines.get(filename)
        )

        for ln, cov in f["coverage"].items():
            _file.append(
                int(ln),
                report_builder_session.create_coverage_line(cov),
            )

        report_builder_session.append(_file)
    return report_builder_session.output_report()
