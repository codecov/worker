import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class SalesforceProcessor(BaseLanguageProcessor):
    def matches_content(self, content: list, first_line: str, name: str) -> bool:
        return bool(content) and isinstance(content, list) and "name" in content[0]

    @sentry_sdk.trace
    def process(
        self, name: str, content: list, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_json(content, report_builder_session)


def from_json(json: list, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )
    for obj in json:
        if obj and obj.get("name") and obj.get("lines"):
            fn = path_fixer(obj["name"] + (".cls" if "." not in obj["name"] else ""))
            if fn is None:
                continue

            _file = report_builder_session.file_class(
                name=fn, ignore=ignored_lines.get(fn)
            )
            for ln, cov in obj["lines"].items():
                _file[int(ln)] = report_builder_session.create_coverage_line(
                    filename=fn, coverage=cov, coverage_type=CoverageType.line
                )

            report_builder_session.append(_file)

    return report_builder_session.output_report()
