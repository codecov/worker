import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import LineSession, ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class JetBrainsXMLProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content.tag == "Root")

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


def from_xml(xml, fix, ignored_lines, sessionid, repo_yaml):
    # dict of {"fileid": "path"}
    file_by_id = {}
    file_by_id_get = file_by_id.get
    for f in xml.iter("File"):
        filename = fix(f.attrib["Name"].replace("\\", "/"))
        if filename:
            file_by_id[str(f.attrib["Index"])] = ReportFile(
                filename, ignore=ignored_lines.get(filename)
            )

    for statement in xml.iter("Statement"):
        _file = file_by_id.get(str(statement.attrib["FileIndex"]))
        if _file is not None:
            sl = int(statement.attrib["Line"])
            el = int(statement.attrib["EndLine"])
            sc = int(statement.attrib["Column"])
            ec = int(statement.attrib["EndColumn"])
            cov = 1 if statement.attrib["Covered"] == "True" else 0
            if sl == el:
                _file.append(
                    sl,
                    ReportLine.create(
                        coverage=cov,
                        sessions=[
                            LineSession(
                                id=sessionid, coverage=cov, partials=[[sc, ec, cov]]
                            )
                        ],
                    ),
                )
            else:
                _file.append(
                    sl, ReportLine.create(coverage=cov, sessions=[[sessionid, cov]])
                )

    report = Report()
    report_append = report.append
    for fid, content in file_by_id.items():
        report_append(content)

    return report
