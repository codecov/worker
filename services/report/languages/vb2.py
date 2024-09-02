from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.path_fixer import PathFixer
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class VbTwoProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "CoverageDSPriv"

    @sentry_sdk.trace
    def process(
        self, name: str, content: Element, report_builder: ReportBuilder
    ) -> Report:
        return from_xml(
            content,
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
        )


def from_xml(xml: Element, fix: PathFixer, ignored_lines: dict, sessionid: int):
    file_by_source = {}
    for source in xml.iter("SourceFileNames"):
        filename = fix(source.find("SourceFileName").text.replace("\\", "/"))
        if filename:
            file_by_source[source.find("SourceFileID").text] = ReportFile(
                filename, ignore=ignored_lines.get(filename)
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
                _file[ln] = ReportLine.create(cov, None, [[sessionid, cov]])

    report = Report()
    for value in file_by_source.values():
        report.append(value)
    return report
