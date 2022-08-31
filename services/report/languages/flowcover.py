import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class FlowcoverProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return isinstance(content, dict) and bool(content.get("flowStatus"))

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        return from_json(content, path_fixer, ignored_lines, sessionid)


def from_json(json, fix, ignored_lines, sessionid):
    report = Report()
    for fn, data in json["files"].items():
        fn = fix(fn)
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

        report.append(_file)

    return report
