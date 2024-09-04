import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class RlangProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and content.get("uploader") == "R"

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def from_json(data_dict: dict, report_builder_session: ReportBuilderSession) -> Report:
    """
    Report example

      uploader: R
      files: []
        name:
        coverage: [null]
    """
    path_fixer, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )

    for data in data_dict["files"]:
        filename = path_fixer(data["name"])
        if filename:
            _file = report_builder_session.file_class(
                name=filename, ignore=ignored_lines.get(filename)
            )

            for ln, cov in enumerate(data["coverage"]):
                if cov:
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            filename=filename,
                            coverage=int(cov),
                            coverage_type=CoverageType.line,
                        ),
                    )

            report_builder_session.append(_file)

    return report_builder_session.output_report()
