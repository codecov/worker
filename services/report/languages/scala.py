import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class ScalaProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return "fileReports" in content

    @sentry_sdk.trace
    def process(
        self, content: dict, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_json(content, report_builder_session)


def from_json(data_dict: dict, report_builder_session: ReportBuilderSession) -> None:
    for f in data_dict["fileReports"]:
        _file = report_builder_session.create_coverage_file(f["filename"])
        if _file is None:
            continue

        for ln, cov in f["coverage"].items():
            _file.append(
                int(ln),
                report_builder_session.create_coverage_line(cov),
            )

        report_builder_session.append(_file)
