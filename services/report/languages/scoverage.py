import sentry_sdk
from lxml.etree import Element
from shared.helpers.numeric import maxint
from shared.reports.resources import ReportFile

from services.report.report_builder import CoverageType, ReportBuilderSession

from .base import BaseLanguageProcessor
from .helpers import child_text


class SCoverageProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "statements"

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    files: dict[str, ReportFile | None] = {}
    for statement in xml.iter("statement"):
        filename = child_text(statement, "source")
        if filename not in files:
            files[filename] = report_builder_session.create_coverage_file(filename)

        _file = files.get(filename)
        if _file is None:
            continue

        # Add the line
        ln = int(child_text(statement, "line"))
        hits = child_text(statement, "count")

        if child_text(statement, "ignored") == "true":
            continue

        if child_text(statement, "branch") == "true":
            cov = "%s/2" % hits
            _file.append(
                ln,
                report_builder_session.create_coverage_line(
                    cov,
                    CoverageType.branch,
                ),
            )
        else:
            cov = maxint(hits)
            _file.append(
                ln,
                report_builder_session.create_coverage_line(
                    cov,
                ),
            )

    for _file in files.values():
        if _file is not None:
            report_builder_session.append(_file)
