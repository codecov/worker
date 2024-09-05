from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class VbTwoProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "CoverageDSPriv"

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    files: dict[str, ReportFile] = {}
    for source in xml.iter("SourceFileNames"):
        _file = report_builder_session.create_coverage_file(
            source.find("SourceFileName").text.replace("\\", "/")
        )
        if _file is not None:
            files[source.find("SourceFileID").text] = _file

    for line in xml.iter("Lines"):
        _file = files.get(line.find("SourceFileID").text)
        if _file is None:
            continue

        # 0 == hit, 1 == partial, 2 == miss
        cov = line.find("Coverage").text
        cov = 1 if cov == "0" else 0 if cov == "2" else True
        for ln in range(
            int(line.find("LnStart").text), int(line.find("LnEnd").text) + 1
        ):
            _file.append(
                ln,
                report_builder_session.create_coverage_line(
                    cov,
                ),
            )

    for _file in files.values():
        report_builder_session.append(_file)
