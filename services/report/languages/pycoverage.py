import typing

from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    SpecialLabelsEnum,
)

COVERAGE_HIT = 1
COVERAGE_MISS = 0


class PyCoverageProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name) -> bool:
        return (
            "meta" in content
            and isinstance(content.get("meta"), dict)
            and "show_contexts" in content.get("meta")
            and "files" in content
        )

    def _convert_testname_to_label(self, testname):
        if testname == "":
            return SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER
        return testname.split("|", 1)[0]

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        for filename, file_coverage in content["files"].items():
            fixed_filename = report_builder.path_fixer(filename)
            if fixed_filename:
                report_file = report_builder_session.file_class(fixed_filename)
                lines_and_coverage = [
                    (COVERAGE_HIT, ln) for ln in file_coverage["executed_lines"]
                ] + [(COVERAGE_MISS, ln) for ln in file_coverage["missing_lines"]]
                for cov, ln in lines_and_coverage:
                    label_list_of_lists = [
                        [self._convert_testname_to_label(testname)]
                        for testname in file_coverage.get("contexts", {}).get(
                            str(ln), []
                        )
                    ]
                    report_file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            fixed_filename,
                            cov,
                            coverage_type=CoverageType.line,
                            labels_list_of_lists=label_list_of_lists,
                        ),
                    )
                report_builder_session.append(report_file)
        return report_builder_session.output_report()
