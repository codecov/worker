from io import BytesIO

import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession


class DLSTProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        return content[-7:] == b"covered"

    @sentry_sdk.trace
    def process(
        self, content: bytes, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_string(content, report_builder_session)


def from_string(string: bytes, report_builder_session: ReportBuilderSession) -> None:
    filename = report_builder_session.filepath
    if filename:
        # src/file.lst => src/file.d
        filename = report_builder_session.path_fixer("%sd" % filename[:-3])

    if not filename:
        # file.d => src/file.d
        last_line = string[string.rfind(b"\n") :].decode(errors="replace").strip()
        filename = last_line.split(" is ", 1)[0]
        if filename.startswith("source "):
            filename = filename[7:]

    _file = report_builder_session.create_coverage_file(filename)
    if _file is None:
        return None

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
