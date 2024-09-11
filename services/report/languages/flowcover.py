import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class FlowcoverProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and bool(content.get("flowStatus"))

    @sentry_sdk.trace
    def process(
        self, content: dict, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_json(content, report_builder_session)


def from_json(json: dict, report_builder_session: ReportBuilderSession) -> None:
    for fn, data in json["files"].items():
        _file = report_builder_session.create_coverage_file(fn)
        if _file is None:
            continue

        for loc in data["expressions"].get("covered_locs", []):
            start, end = loc["start"], loc["end"]
            partials = (
                [[start["column"], end["column"], 1]]
                if start["line"] == end["line"]
                else None
            )
            _file.append(
                start["line"],
                report_builder_session.create_coverage_line(
                    1,
                    partials=partials,
                ),
            )

        for loc in data["expressions"].get("uncovered_locs", []):
            start, end = loc["start"], loc["end"]
            partials = (
                [[start["column"], end["column"], 0]]
                if start["line"] == end["line"]
                else None
            )
            _file.append(
                start["line"],
                report_builder_session.create_coverage_line(
                    0,
                    partials=partials,
                ),
            )

        report_builder_session.append(_file)
