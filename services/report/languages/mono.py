from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class MonoProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "coverage" and content.find("assembly") is not None

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    files: dict[str, ReportFile | None] = {}

    # loop through methods
    for method in xml.iter("method"):
        filename = method.attrib["filename"]
        if filename not in files:
            _file = report_builder_session.create_coverage_file(filename)
            files[filename] = _file

        _file = files[filename]
        if _file is None:
            continue

        # loop through statements
        for line in method.iter("statement"):
            attr = line.attrib
            coverage = int(attr["counter"])

            _file.append(
                int(attr["line"]),
                report_builder_session.create_coverage_line(
                    coverage,
                ),
            )

    for _file in files.values():
        if _file is not None:
            report_builder_session.append(_file)
