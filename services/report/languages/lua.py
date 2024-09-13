import re

import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class LuaProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        return content[:7] == b"======="

    @sentry_sdk.trace
    def process(
        self, content: bytes, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_txt(content, report_builder_session)


docs = re.compile(r"^=+\n", re.M).split


def from_txt(input: bytes, report_builder_session: ReportBuilderSession) -> None:
    _file = None
    for line in docs(input.decode(errors="replace").replace("\t", " ")):
        line = line.rstrip()
        if line == "Summary":
            _file = None

        elif line.endswith((".lua", ".lisp")):
            _file = report_builder_session.create_coverage_file(line)

        elif _file is not None:
            for ln, source in enumerate(line.splitlines(), start=1):
                try:
                    cov = source.strip().split(" ")[0]
                    cov = 0 if cov[-2:] in ("*0", "0") else int(cov)
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            cov,
                        ),
                    )

                except Exception:
                    pass

            report_builder_session.append(_file)
