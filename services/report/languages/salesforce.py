import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class SalesforceProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content) and isinstance(content, list) and "name" in content[0]

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_json(content, report_builder_session)


def from_json(json, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, sessionid = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.sessionid,
    )
    for obj in json:
        if obj and obj.get("name") and obj.get("lines"):
            fn = path_fixer(obj["name"] + (".cls" if "." not in obj["name"] else ""))
            if fn is None:
                continue

            _file = ReportFile(fn, ignore=ignored_lines.get(fn))
            for ln, cov in obj["lines"].items():
                _file[int(ln)] = ReportLine.create(
                    coverage=cov, sessions=[[sessionid, cov]]
                )

            report_builder_session.append(_file)

    return report_builder_session.output_report()
