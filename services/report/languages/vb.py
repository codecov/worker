from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    ReportBuilder,
    ReportBuilderSession,
)


class VbProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "results"

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

    for module in xml.iter("module"):
        file_by_source = {}
        # loop through sources
        for sf in module.iter("source_file"):
            filename = path_fixer(sf.attrib["path"].replace("\\", "/"))
            if filename:
                file_by_source[sf.attrib["id"]] = report_builder_session.file_class(
                    name=filename, ignore=ignored_lines.get(filename)
                )

        if file_by_source:
            # loop through each line
            for line in module.iter("range"):
                line = line.attrib
                _file = file_by_source.get(line["source_id"])
                if _file is not None:
                    coverage = line["covered"]
                    coverage = (
                        1 if coverage == "yes" else 0 if coverage == "no" else True
                    )
                    for ln in range(int(line["start_line"]), int(line["end_line"]) + 1):
                        _file.append(
                            ln,
                            report_builder_session.create_coverage_line(
                                coverage,
                            ),
                        )

            # add files
            for v in file_by_source.values():
                report_builder_session.append(v)

    return report_builder_session.output_report()
