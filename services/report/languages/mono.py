from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    ReportBuilder,
    ReportBuilderSession,
)


class MonoProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "coverage" and content.find("assembly") is not None

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
    # loop through methods
    for method in xml.iter("method"):
        # get file name
        filename = path_fixer(method.attrib["filename"])
        if filename is None:
            continue

        _file = report_builder_session.get_file(filename)
        if not _file:
            _file = report_builder_session.file_class(
                name=filename, ignore=ignored_lines.get(filename)
            )

        # loop through statements
        for line in method.iter("statement"):
            line = line.attrib
            coverage = int(line["counter"])

            _file.append(
                int(line["line"]),
                report_builder_session.create_coverage_line(
                    coverage,
                ),
            )

        report_builder_session.append(_file)

    return report_builder_session.output_report()
