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
        labels_table = LabelsTable(report_builder_session, content)

        for filename, file_coverage in content["files"].items():
            _file = report_builder_session.create_coverage_file(filename)
            if _file is None:
                continue

            lines_and_coverage = [
                (COVERAGE_HIT, ln) for ln in file_coverage["executed_lines"]
            ] + [(COVERAGE_MISS, ln) for ln in file_coverage["missing_lines"]]
            for cov, ln in lines_and_coverage:
                if ln > 0:
                    label_list_of_lists: list[list[str]] | list[list[int]] = []
                    if report_builder_session.should_use_label_index:
                        label_list_of_lists = [
                            [single_id]
                            for single_id in labels_table._get_list_of_label_ids(
                                report_builder_session.label_index,
                                file_coverage.get("contexts", {}).get(str(ln), []),
                            )
                        ]
                    else:
                        label_list_of_lists = [
                            [labels_table._normalize_label(testname)]
                            for testname in file_coverage.get("contexts", {}).get(
                                str(ln), []
                            )
                        ]
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            cov,
                            labels_list_of_lists=label_list_of_lists,
                        ),
                    )
            report_builder_session.append(_file)


class LabelsTable:
    def __init__(
        self, report_builder_session: ReportBuilderSession, content: dict
    ) -> None:
        self.labels_table: dict[str, str] = {}
        self.reverse_table: dict[str, int] = {}
        self.are_labels_already_encoded = False

        # Compressed pycoverage files will include a labels_table
        if "labels_table" in content:
            self.labels_table = content["labels_table"]
            # We can pre-populate some of the indexes that will be used
            for idx, testname in self.labels_table.items():
                clean_label = self._normalize_label(testname)
                report_builder_session.label_index[int(idx)] = clean_label
            self.are_labels_already_encoded = True

    def _normalize_label(self, testname: int | float | str) -> str:
        if isinstance(testname, int) or isinstance(testname, float):
            # This is from a compressed report.
            # Pull label from the labels_table
            # But the labels_table keys are strings, because of JSON format
            testname = self.labels_table[str(testname)]
        if testname == "":
            return SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label
        return testname.split("|", 1)[0]

    def _get_list_of_label_ids(
        self,
        current_label_idx: dict[int, str],
        line_contexts: list[str | int],
    ) -> list[int]:
        if self.are_labels_already_encoded:
            # The line contexts already include indexes in the table.
            # We can re-use the table and don't have to do anything with contexts.
            return sorted(map(int, line_contexts))

        # In this case we do need to fix the labels
        label_ids_for_line = set()
        for testname in line_contexts:
            clean_label = self._normalize_label(testname)
            if clean_label in self.reverse_table:
                label_ids_for_line.add(self.reverse_table[clean_label])
            else:
                label_id = max([*current_label_idx.keys(), 0]) + 1
                current_label_idx[label_id] = clean_label
                self.reverse_table[clean_label] = label_id
                label_ids_for_line.add(label_id)

        return sorted(label_ids_for_line)
