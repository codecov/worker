import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class ScalaProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return "fileReports" in content

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


def from_json(data_dict, fix, ignored_lines, sessionid):
    report = Report()
    for f in data_dict["fileReports"]:
        filename = fix(f["filename"])
        if filename is None:
            continue
        _file = ReportFile(filename, ignore=ignored_lines.get(filename))
        fs = _file.__setitem__
        for ln, cov in f["coverage"].items():
            fs(int(ln), ReportLine.create(cov, None, [[sessionid, cov]]))
        report.append(_file)
    return report
