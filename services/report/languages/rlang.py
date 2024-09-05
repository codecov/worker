import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class RlangProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and content.get("uploader") == "R"

    @sentry_sdk.trace
    def process(
        self, content: dict, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_json(content, report_builder_session)


def from_json(data_dict: dict, report_builder_session: ReportBuilderSession) -> None:
    """
    Report example

      uploader: R
      files: []
        name:
        coverage: [null]
    """

    for data in data_dict["files"]:
        _file = report_builder_session.create_coverage_file(data["name"])
        if _file is None:
            continue

        for ln, cov in enumerate(data["coverage"]):
            if cov:
                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(
                        int(cov),
                    ),
                )

        report_builder_session.append(_file)
