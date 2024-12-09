import logging
from base64 import b64encode
from decimal import Decimal
from typing import List

from shared.reports.resources import Report

from helpers.reports import get_totals_from_file_in_reports
from services.comparison import ComparisonProxy
from services.notification.notifiers.mixins.message.helpers import (
    ellipsis,
    escape_markdown,
    make_patch_only_metrics,
)

log = logging.getLogger(__name__)


# Unlike sections.py, this is an alternative take for creating messages based functionality.
# This is a plan specific section, so it doesn't adhere to the settings/yaml configurations
# like other writers do, hence the new file
class TeamPlanWriter:
    @property
    def name(self):
        return self.__class__.__name__

    def header_lines(self, comparison: ComparisonProxy, diff, settings) -> List[str]:
        lines = []

        head_report = comparison.head.report
        diff_totals = head_report.apply_diff(diff)

        if diff_totals:
            misses_and_partials = diff_totals.misses + diff_totals.partials
            patch_coverage = diff_totals.coverage
        else:
            misses_and_partials = None
            patch_coverage = None
        if misses_and_partials:
            ln_text = "lines" if misses_and_partials > 1 else "line"
            lines.append(
                f"Attention: Patch coverage is `{patch_coverage}%` with `{misses_and_partials} {ln_text}` in your changes missing coverage. Please review."
            )
        else:
            lines.append(
                "All modified and coverable lines are covered by tests :white_check_mark:"
            )

        hide_project_coverage = settings.get("hide_project_coverage", False)
        if hide_project_coverage:
            if comparison.test_results_error():
                lines.append("")
                lines.append(
                    ":x: We are unable to process any of the uploaded JUnit XML files. Please ensure your files are in the right format."
                )
            elif comparison.all_tests_passed():
                lines.append("")
                lines.append(
                    ":white_check_mark: All tests successful. No failed tests found."
                )

        return lines

    def middle_lines(
        self, comparison: ComparisonProxy, diff, links, current_yaml
    ) -> List[str]:
        lines = []

        # create list of files changed in diff
        base_report = comparison.project_coverage_base.report
        head_report = comparison.head.report
        if base_report is None:
            base_report = Report()
        files_in_diff = [
            (
                _diff["type"],
                path,
                make_patch_only_metrics(
                    get_totals_from_file_in_reports(base_report, path) or False,
                    get_totals_from_file_in_reports(head_report, path) or False,
                    _diff["totals"],
                    # show_complexity defaulted to none
                    None,
                    current_yaml,
                    links["pull"],
                ),
                int(_diff["totals"].misses + _diff["totals"].partials),
            )
            for path, _diff in (diff["files"] if diff else {}).items()
            if _diff.get("totals")
        ]

        if files_in_diff:
            table_header = "| Patch % | Lines |"
            table_layout = "|---|---|---|"

            # get limit of results to show
            limit = 10
            mentioned = []

            def tree_cell(typ, path, metrics, _=None):
                if path not in mentioned:
                    # mentioned: for files that are in diff and changes
                    mentioned.append(path)
                    return "| {rm}[{path}]({compare}?src=pr&el=tree#diff-{hash}){rm} {metrics}".format(
                        rm="~~" if typ == "deleted" else "",
                        path=escape_markdown(ellipsis(path, 50, False)),
                        compare=links["pull"],
                        hash=b64encode(path.encode()).decode(),
                        metrics=metrics,
                    )

            remaining_files = 0
            printed_files = 0
            changed_files = sorted(
                files_in_diff, key=lambda a: a[3] or Decimal("0"), reverse=True
            )
            changed_files_with_missing_lines = [f for f in changed_files if f[3] > 0]
            if changed_files_with_missing_lines:
                lines.append(
                    "| [Files with missing lines]({0}?dropdown=coverage&src=pr&el=tree) {1}".format(
                        links["pull"], table_header
                    )
                )
                lines.append(table_layout)
            for file in changed_files_with_missing_lines:
                if printed_files == limit:
                    remaining_files += 1
                else:
                    printed_files += 1
                    lines.append(tree_cell(file[0], file[1], file[2]))
            if remaining_files:
                lines.append(
                    "| ... and [{n} more]({href}?src=pr&el=tree-more) | |".format(
                        n=remaining_files, href=links["pull"]
                    )
                )

        return lines

    def footer_lines(self) -> List[str]:
        lines = []
        lines.append("")
        lines.append(
            ":loudspeaker: Thoughts on this report? [Let us know!]({0})".format(
                "https://github.com/codecov/feedback/issues/255"
            )
        )

        return lines
