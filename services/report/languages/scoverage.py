from xml.etree.ElementTree import Element

import sentry_sdk
from shared.helpers.numeric import maxint
from shared.reports.resources import Report,ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class SCoverageProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "statements"

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
            _file = files.get(filename)
            if not _file:
                _file = report_builder_session.file_class(
                    name=filename, ignore=ignored_lines.get(filename)
                )
                files[filename] = _file

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
            _file.append(ln, report_builder_session.create_coverage_line(
                filename=filename,
                coverage=cov,
                coverage_type=CoverageType.branch,
            ))
        else:
            cov = maxint(hits)
            _file.append(ln, report_builder_session.create_coverage_line(
                filename=filename,
                coverage=cov,
                coverage_type=CoverageType.line,
            ))

    for v in files.values():
        report_builder_session.append(v)

    return report_builder_session.output_report()
