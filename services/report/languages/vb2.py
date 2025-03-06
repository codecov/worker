import sentry_sdk
from lxml.etree import Element
from shared.reports.resources import ReportFile

from services.report.report_builder import ReportBuilderSession

from .base import BaseLanguageProcessor
from .helpers import child_text


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
    for source in xml.iterfind("SourceFileNames"):
        _file = report_builder_session.create_coverage_file(
            child_text(source, "SourceFileName").replace("\\", "/")
        )
        if _file is not None:
            files[child_text(source, "SourceFileID")] = _file

    for line in xml.iterfind("Lines"):
        _file = files.get(child_text(line, "SourceFileID"))
        if _file is None:
            continue

        # 0 == hit, 1 == partial, 2 == miss
        cov_txt = child_text(line, "Coverage")
        cov = 1 if cov_txt == "0" else 0 if cov_txt == "2" else True
        for ln in range(
            int(child_text(line, "LnStart")),
            int(child_text(line, "LnEnd")) + 1,
        ):
            _file.append(
                ln,
                report_builder_session.create_coverage_line(
                    cov,
                ),
            )

    for _file in files.values():
        report_builder_session.append(_file)
