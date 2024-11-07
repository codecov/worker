import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilderSession, SpecialLabelsEnum

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
        labels_table = content.get("labels_table", {})

        for filename, file_coverage in content["files"].items():
            _file = report_builder_session.create_coverage_file(filename)
            if _file is None:
                continue

            lines_and_coverage = [
                (COVERAGE_HIT, ln) for ln in file_coverage["executed_lines"]
            ] + [(COVERAGE_MISS, ln) for ln in file_coverage["missing_lines"]]
            for cov, ln in lines_and_coverage:
                if ln > 0:
                    label_list_of_lists = [
                        [_normalize_label(labels_table, testname)]
                        for testname in file_coverage.get("contexts", {}).get(
                            str(ln), []
                        )
                    ]
                    _line = report_builder_session.create_coverage_line(
                        cov,
                        labels_list_of_lists=label_list_of_lists,
                    )
                    _file.append(ln, _line)
            report_builder_session.append(_file)


def _normalize_label(labels_table: dict[str, str], testname: int | float | str) -> str:
    if isinstance(testname, int) or isinstance(testname, float):
        # This is from a compressed report.
        # Pull label from the labels_table
        # But the labels_table keys are strings, because of JSON format
        testname = labels_table[str(testname)]
    if testname == "":
        return SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label
    return testname.split("|", 1)[0]
