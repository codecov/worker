from io import BytesIO

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    ReportBuilder,
    ReportBuilderSession,
)


class DLSTProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        return content[-7:] == b"covered"

    @sentry_sdk.trace
    def process(
        self, name: str, content: bytes, report_builder: ReportBuilder
    ) -> Report:
        return from_string(content, report_builder.create_report_builder_session(name))


def from_string(string: bytes, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, filename = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.filepath,
    )
    if filename:
        # src/file.lst => src/file.d
        filename = path_fixer("%sd" % filename[:-3])

    if not filename:
        # file.d => src/file.d
        last_line = string[string.rfind(b"\n") :].decode(errors="replace").strip()
        filename = last_line.split(" is ", 1)[0]
        if filename.startswith("source "):
            filename = filename[7:]

        filename = path_fixer(filename)
        if not filename:
            return None

    _file = report_builder_session.file_class(
        filename, ignore=ignored_lines.get(filename)
    )
    for ln, encoded_line in enumerate(BytesIO(string), start=1):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        try:
            coverage = int(line.split("|", 1)[0].strip())
            _file.append(
                ln,
                report_builder_session.create_coverage_line(
                    coverage,
                ),
            )
        except Exception:
            # not a vaild line
            pass

    report_builder_session.append(_file)
    return report_builder_session.output_report()
