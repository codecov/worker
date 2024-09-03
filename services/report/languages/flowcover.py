import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class FlowcoverProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and bool(content.get("flowStatus"))

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(
            filepath=name
        )
        return from_json(content, report_builder_session)


def from_json(json: dict, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )

    for fn, data in json["files"].items():
        fn = path_fixer(fn)
        if fn is None:
            continue

        _file = report_builder_session.file_class(name=fn, ignore=ignored_lines.get(fn))

        for loc in data["expressions"].get("covered_locs", []):
            start, end = loc["start"], loc["end"]
            partials = (
                [[start["column"], end["column"], 1]]
                if start["line"] == end["line"]
                else None
            )
            _file[start["line"]] = report_builder_session.create_coverage_line(
                filename=fn,
                coverage=1,
                coverage_type=CoverageType.line,
                partials=partials,
            )

        for loc in data["expressions"].get("uncovered_locs", []):
            start, end = loc["start"], loc["end"]
            partials = (
                [[start["column"], end["column"], 0]]
                if start["line"] == end["line"]
                else None
            )
            _file[start["line"]] = report_builder_session.create_coverage_line(
                filename=fn,
                coverage=0,
                coverage_type=CoverageType.line,
                partials=partials,
            )

        report_builder_session.append(_file)

    return report_builder_session.output_report()
