from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report, ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class VbProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "results"

    @sentry_sdk.trace
    def process(
        self, name: str, content: Element, report_builder: ReportBuilder
    ) -> Report:
        return from_xml(content, report_builder.create_report_builder_session(name))


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> Report:
    files: dict[str, ReportFile] = {}
    for module in xml.iter("module"):
        # loop through sources
        for sf in module.iter("source_file"):
            _file = report_builder_session.create_coverage_file(
                sf.attrib["path"].replace("\\", "/")
            )
            if _file is not None:
                files[sf.attrib["id"]] = _file

        # loop through each line
        for line in module.iter("range"):
            line = line.attrib
            _file = files.get(line["source_id"])
            if _file is None:
                continue

            coverage = line["covered"]
            coverage = 1 if coverage == "yes" else 0 if coverage == "no" else True
            for ln in range(int(line["start_line"]), int(line["end_line"]) + 1):
                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(
                        coverage,
                    ),
                )

    # add files
    for _file in files.values():
        report_builder_session.append(_file)

    return report_builder_session.output_report()
