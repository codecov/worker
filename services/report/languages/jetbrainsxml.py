from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report, ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class JetBrainsXMLProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "Root"

    @sentry_sdk.trace
    def process(
        self, name: str, content: Element, report_builder: ReportBuilder
    ) -> Report:
        return from_xml(content, report_builder.create_report_builder_session(name))


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )

    file_by_id: dict[str, ReportFile] = {}
    for f in xml.iter("File"):
        filename = path_fixer(f.attrib["Name"].replace("\\", "/"))
        if filename:
            file_by_id[str(f.attrib["Index"])] = report_builder_session.file_class(
                name=filename, ignore=ignored_lines.get(filename)
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
                    report_builder_session.create_coverage_line(
                        filename=filename,
                        coverage=cov,
                        coverage_type=CoverageType.line,
                        partials=[[sc, ec, cov]],
                    ),
                )
            else:
                _file.append(
                    sl,
                    report_builder_session.create_coverage_line(
                        filename=filename,
                        coverage=cov,
                        coverage_type=CoverageType.line,
                    ),
                )

    for content in file_by_id.values():
        report_builder_session.append(content)

    return report_builder_session.output_report()
