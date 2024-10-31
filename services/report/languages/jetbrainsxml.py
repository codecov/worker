from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class JetBrainsXMLProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "Root"

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    file_by_id: dict[str, ReportFile] = {}
    for f in xml.iter("File"):
        filename = f.attrib["Name"].replace("\\", "/")
        _file = report_builder_session.create_coverage_file(filename)
        if _file is not None:
            file_by_id[str(f.attrib["Index"])] = _file

    for statement in xml.iter("Statement"):
        _file = file_by_id.get(str(statement.attrib["FileIndex"]))
        if _file is None:
            continue

        sl = int(statement.attrib["Line"])
        el = int(statement.attrib["EndLine"])
        sc = int(statement.attrib["Column"])
        ec = int(statement.attrib["EndColumn"])
        cov = 1 if statement.attrib["Covered"] == "True" else 0
        if sl == el:
            _file.append(
                sl,
                report_builder_session.create_coverage_line(
                    cov,
                    partials=[[sc, ec, cov]],
                ),
            )
        else:
            _file.append(
                sl,
                report_builder_session.create_coverage_line(
                    cov,
                ),
            )

    for content in file_by_id.values():
        report_builder_session.append(content)
