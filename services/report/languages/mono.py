import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class MonoProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content.tag == "coverage" and content.find("assembly") is not None)

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        return from_xml(content, path_fixer, ignored_lines, sessionid, repo_yaml)


def from_xml(xml, fix, ignored_lines, sessionid, yaml):
    report = Report()

    # loop through methods
    for method in xml.iter("method"):
        # get file name
        filename = fix(method.attrib["filename"])
        if filename is None:
            continue

        # get file
        _file = report.get(filename)
        if not _file:
            _file = ReportFile(filename, ignore=ignored_lines.get(filename))

        # loop through statements
        for line in method.iter("statement"):
            line = line.attrib
            coverage = int(line["counter"])

            _file.append(
                int(line["line"]),
                ReportLine.create(coverage=coverage, sessions=[[sessionid, coverage]]),
            )

        report.append(_file)

    return report
