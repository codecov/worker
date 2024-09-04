from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class VbTwoProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "CoverageDSPriv"

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

    file_by_source = {}
    for source in xml.iter("SourceFileNames"):
        filename = path_fixer(source.find("SourceFileName").text.replace("\\", "/"))
        if filename:
            file_by_source[source.find("SourceFileID").text] = (
                report_builder_session.file_class(
                    name=filename, ignore=ignored_lines.get(filename)
                )
            )

    for line in xml.iter("Lines"):
        _file = file_by_source.get(line.find("SourceFileID").text)
        if _file is not None:
            # 0 == hit, 1 == partial, 2 == miss
            cov = line.find("Coverage").text
            cov = 1 if cov == "0" else 0 if cov == "2" else True
            for ln in range(
                int(line.find("LnStart").text), int(line.find("LnEnd").text) + 1
            ):
                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(
                        filename=_file.name,
                        coverage=cov,
                        coverage_type=CoverageType.line,
                    ),
                )

    for value in file_by_source.values():
        report_builder_session.append(value)

    return report_builder_session.output_report()
