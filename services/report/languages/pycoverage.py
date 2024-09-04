from typing import Dict, List, Optional, Union

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    ReportBuilder,
    SpecialLabelsEnum,
)

COVERAGE_HIT = 1
COVERAGE_MISS = 0


class PyCoverageProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return (
            "meta" in content
            and "files" in content
            and isinstance(content.get("meta"), dict)
            and "show_contexts" in content.get("meta")
        )

    def _normalize_label(self, testname) -> str:
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
        current_label_idx: Optional[Dict[int, str]],
        line_contexts: List[Union[str, int]] = None,
    ) -> List[int]:
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

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)

        # Compressed pycoverage files will include a labels_table
        # Mapping label_idx: int --> label: str
        self.labels_table: Dict[int, str] = None
        self.reverse_table = {}
        self.are_labels_already_encoded = False
        if "labels_table" in content:
            self.labels_table = content["labels_table"]
            # We can pre-populate some of the indexes that will be used
            for idx, testname in self.labels_table.items():
                clean_label = self._normalize_label(testname)
                report_builder_session.label_index[int(idx)] = clean_label
            self.are_labels_already_encoded = True

        for filename, file_coverage in content["files"].items():
            fixed_filename = report_builder.path_fixer(filename)
            if fixed_filename:
                report_file = report_builder_session.file_class(fixed_filename)
                lines_and_coverage = [
                    (COVERAGE_HIT, ln) for ln in file_coverage["executed_lines"]
                ] + [(COVERAGE_MISS, ln) for ln in file_coverage["missing_lines"]]
                for cov, ln in lines_and_coverage:
                    if report_builder_session.should_use_label_index:
                        label_list_of_lists = [
                            [single_id]
                            for single_id in self._get_list_of_label_ids(
                                report_builder_session.label_index,
                                file_coverage.get("contexts", {}).get(str(ln), []),
                            )
                        ]
                    else:
                        label_list_of_lists = [
                            [self._normalize_label(testname)]
                            for testname in file_coverage.get("contexts", {}).get(
                                str(ln), []
                            )
                        ]
                    if ln > 0:
                        report_file.append(
                            ln,
                            report_builder_session.create_coverage_line(
                                cov,
                                labels_list_of_lists=label_list_of_lists,
                            ),
                        )
                report_builder_session.append(report_file)
        # We don't need these anymore, so let them be removed by the garbage collector
        self.reverse_table = None
        self.labels_table = None
        return report_builder_session.output_report()
