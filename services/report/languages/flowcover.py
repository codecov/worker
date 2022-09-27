import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class FlowcoverProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return isinstance(content, dict) and bool(content.get("flowStatus"))

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(
            filepath=name
        )
        return from_json(content, report_builder_session)


def from_json(json, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, sessionid = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.sessionid,
    )

    for fn, data in json["files"].items():
        fn = path_fixer(fn)
        if fn is None:
            continue

        _file = ReportFile(fn, ignore=ignored_lines.get(fn))

        for loc in data["expressions"].get("covered_locs", []):
            start, end = loc["start"], loc["end"]
            partials = (
                [[start["column"], end["column"], 1]]
                if start["line"] == end["line"]
                else None
            )
            _file[start["line"]] = ReportLine.create(
                coverage=1, sessions=[[sessionid, 1, None, partials]]
            )

        for loc in data["expressions"].get("uncovered_locs", []):
            start, end = loc["start"], loc["end"]
            partials = (
                [[start["column"], end["column"], 0]]
                if start["line"] == end["line"]
                else None
            )
            _file[start["line"]] = ReportLine.create(
                coverage=0, sessions=[[sessionid, 0, None, partials]]
            )

        report_builder_session.append(_file)

    return report_builder_session.output_report()
