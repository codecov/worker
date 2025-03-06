import sentry_sdk
from lxml.etree import Element
from shared.reports.resources import ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class VbProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "results"

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
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
            attr = line.attrib
            _file = files.get(attr["source_id"])
            if _file is None:
                continue

            cov_txt = attr["covered"]
            coverage = 1 if cov_txt == "yes" else 0 if cov_txt == "no" else True
            for ln in range(int(attr["start_line"]), int(attr["end_line"]) + 1):
                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(
                        coverage,
                    ),
                )

    # add files
    for _file in files.values():
        report_builder_session.append(_file)
