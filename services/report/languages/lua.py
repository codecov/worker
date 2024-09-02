import re

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class LuaProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        return content[:7] == b"======="

    @sentry_sdk.trace
    def process(
        self, name: str, content: bytes, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_txt(content, report_builder_session)


docs = re.compile(r"^=+\n", re.M).split


def from_txt(string: bytes, report_builder_session: ReportBuilderSession) -> Report:
    filename = None
    ignored_lines = report_builder_session.ignored_lines
    for string in docs(string.decode(errors="replace").replace("\t", " ")):
        string = string.rstrip()
        if string == "Summary":
            filename = None
            continue

        elif string.endswith((".lua", ".lisp")):
            filename = report_builder_session.path_fixer(string)
            if filename is None:
                continue

        elif filename:
            _file = report_builder_session.file_class(
                filename, ignore=ignored_lines.get(filename)
            )
            for ln, source in enumerate(string.splitlines(), start=1):
                try:
                    cov = source.strip().split(" ")[0]
                    cov = 0 if cov[-2:] in ("*0", "0") else int(cov)
                    _file[ln] = report_builder_session.create_coverage_line(
                        filename=filename, coverage=cov, coverage_type=CoverageType.line
                    )

                except Exception:
                    pass

            report_builder_session.append(_file)

    return report_builder_session.output_report()
