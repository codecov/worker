from xml.etree.ElementTree import Element

import sentry_sdk
from shared.helpers.numeric import maxint
from shared.reports.resources import ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession


class SCoverageProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "statements"

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    path_fixer = report_builder_session.path_fixer

    ignore = []
    cache_fixes = {}
    _cur_file_name = None
    files: dict[str, ReportFile] = {}
    for statement in xml.iter("statement"):
        # Determine the path
        unfixed_path = next(statement.iter("source")).text
        if unfixed_path in ignore:
            continue

        elif unfixed_path in cache_fixes:
            # cached results
            filename = cache_fixes[unfixed_path]

        else:
            # fix path
            filename = path_fixer(unfixed_path)
            if filename is None:
                # add unfixed to list of ignored
                ignore.append(unfixed_path)
                continue

            # cache result (unfixed => filenmae)
            cache_fixes[unfixed_path] = filename

        # Get the file
        if filename != _cur_file_name:
            _cur_file_name = filename
            if filename not in files:
                _file = report_builder_session.create_coverage_file(
                    filename, do_fix_path=False
                )
                files[filename] = _file
            _file = files[filename]

        # Add the line
        ln = int(next(statement.iter("line")).text)
        hits = next(statement.iter("count")).text
        try:
            if next(statement.iter("ignored")).text == "true":
                continue
        except StopIteration:
            pass

        if next(statement.iter("branch")).text == "true":
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
        report_builder_session.append(_file)
