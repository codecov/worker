import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class ScalaProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return "fileReports" in content

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_json(content, report_builder_session)


def from_json(data_dict, report_builder_session: ReportBuilderSession) -> Report:
    ignored_lines, sessionid = (
        report_builder_session.ignored_lines,
        report_builder_session.sessionid,
    )
    for f in data_dict["fileReports"]:
        filename = report_builder_session.path_fixer(f["filename"])
        if filename is None:
            continue
        _file = ReportFile(filename, ignore=ignored_lines.get(filename))
        fs = _file.__setitem__
        for ln, cov in f["coverage"].items():
            fs(int(ln), ReportLine.create(cov, None, [[sessionid, cov]]))
        report_builder_session.append(_file)
    return report_builder_session.output_report()
