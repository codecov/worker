import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession

COVERAGE_HIT = 1
COVERAGE_MISS = 0


class PyCoverageProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        meta = "meta" in content and content["meta"]
        return "files" in content and isinstance(meta, dict) and "show_contexts" in meta

    @sentry_sdk.trace
    def process(
        self, content: dict, report_builder_session: ReportBuilderSession
    ) -> None:
        for filename, file_coverage in content["files"].items():
            _file = report_builder_session.create_coverage_file(filename)
            if _file is None:
                continue

            lines_and_coverage = [
                (COVERAGE_HIT, ln) for ln in file_coverage["executed_lines"]
            ] + [(COVERAGE_MISS, ln) for ln in file_coverage["missing_lines"]]
            for cov, ln in lines_and_coverage:
                if ln > 0:
                    _line = report_builder_session.create_coverage_line(cov)
                    _file.append(ln, _line)
            report_builder_session.append(_file)
