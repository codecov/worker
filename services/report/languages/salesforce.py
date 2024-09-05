import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class SalesforceProcessor(BaseLanguageProcessor):
    def matches_content(self, content: list, first_line: str, name: str) -> bool:
        return bool(content) and isinstance(content, list) and "name" in content[0]

    @sentry_sdk.trace
    def process(
        self, name: str, content: list, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def from_json(json: list, report_builder_session: ReportBuilderSession) -> Report:
    for obj in json:
        if obj and obj.get("name") and obj.get("lines"):
            filename = obj["name"] + (".cls" if "." not in obj["name"] else "")
            _file = report_builder_session.create_coverage_file(filename)
            if _file is None:
                continue

            for ln, cov in obj["lines"].items():
                _file.append(
                    int(ln),
                    report_builder_session.create_coverage_line(cov),
                )

            report_builder_session.append(_file)

    return report_builder_session.output_report()
