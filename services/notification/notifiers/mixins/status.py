import logging
from decimal import Decimal, InvalidOperation

from services.comparison import ComparisonProxy, FilteredComparison
from services.comparison.types import Comparison
from services.yaml.reader import round_number

log = logging.getLogger(__name__)


class StatusPatchMixin(object):
    def get_patch_status(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[str, str]:
        threshold = self.notifier_yaml_settings.get("threshold", "0.0")

        # check if user has erroneously added a % to this input and fix
        if isinstance(threshold, str) and threshold[-1] == "%":
            threshold = threshold[:-1]

        try:
            threshold = Decimal(threshold)
        except (InvalidOperation, TypeError):
            threshold = Decimal("0.0")

        target_coverage: Decimal | None
        totals = comparison.get_patch_totals()
        if self.notifier_yaml_settings.get("target") not in ("auto", None):
            target_coverage = Decimal(
                str(self.notifier_yaml_settings.get("target")).replace("%", "")
            )
        else:
            target_coverage = (
                Decimal(comparison.project_coverage_base.report.totals.coverage)
                if comparison.has_project_coverage_base_report()
                and comparison.project_coverage_base.report.totals.coverage is not None
                else None
            )
        if totals and totals.lines > 0:
            coverage = Decimal(totals.coverage)
            if target_coverage is None:
                state = self.notifier_yaml_settings.get("if_not_found", "success")
                message = "No report found to compare against"
            else:
                state = "success" if coverage >= target_coverage else "failure"
                if (
                    state == "failure"
                    and threshold is not None
                    and coverage >= (target_coverage - threshold)
                ):
                    state = "success"
                    coverage_str = round_number(self.current_yaml, coverage)
                    threshold_str = round_number(self.current_yaml, threshold)
                    target_str = round_number(self.current_yaml, target_coverage)
                    message = f"{coverage_str}% of diff hit (within {threshold_str}% threshold of {target_str}%)"

                else:
                    coverage_str = round_number(self.current_yaml, coverage)
                    target_str = round_number(self.current_yaml, target_coverage)
                    message = f"{coverage_str}% of diff hit (target {target_str}%)"
            return (state, message)
        if comparison.project_coverage_base.commit:
            description = "Coverage not affected when comparing {0}...{1}".format(
                comparison.project_coverage_base.commit.commitid[:7],
                comparison.head.commit.commitid[:7],
            )
        else:
            description = "Coverage not affected"
        return ("success", description)


class StatusChangesMixin(object):
    def is_a_change_worth_noting(self, change) -> bool:
        if not change.new and not change.deleted:
            # has totals and not -10m => 10h
            t = change.totals
            if t:
                # new missed||partial lines
                return (t.misses + t.partials) > 0
        return False

    def get_changes_status(self, comparison: Comparison) -> tuple[str, str]:
        pull = comparison.pull
        if self.notifier_yaml_settings.get("base") in ("auto", None, "pr") and pull:
            if not comparison.has_project_coverage_base_report():
                description = (
                    "Unable to determine changes, no report found at pull request base"
                )
                state = "success"
                return (state, description)

        # filter changes
        changes = comparison.get_changes()
        if changes:
            changes = list(filter(self.is_a_change_worth_noting, changes))

        # remove new additions
        if changes:
            lpc = len(changes)
            eng = "files have" if lpc > 1 else "file has"
            description = (
                "{0} {1} indirect coverage changes not visible in diff".format(lpc, eng)
            )
            state = (
                "success"
                if self.notifier_yaml_settings.get("informational")
                else "failure"
            )
            return (state, description)

        description = "No indirect coverage changes found"
        return ("success", description)


class StatusProjectMixin(object):
    DEFAULT_REMOVED_CODE_BEHAVIOR = "adjust_base"

    def _apply_removals_only_behavior(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[str, str] | None:
        """
        Rule for passing project status on removals_only behavior:
        Pass if code was _only removed_ (i.e. no addition, no unexpected changes)
        """
        log.info(
            "Applying removals_only behavior to project status",
            extra=dict(commit=comparison.head.commit.commitid),
        )
        impacted_files = comparison.get_impacted_files().get("files", [])

        no_added_no_unexpected_change = all(
            not file.get("added_diff_coverage")
            and not file.get("unexpected_line_changes")
            for file in impacted_files
        )
        some_removed = any(file.get("removed_diff_coverage") for file in impacted_files)

        if no_added_no_unexpected_change and some_removed:
            return ("success", ", passed because this change only removed code")
        return None

    def _apply_adjust_base_behavior(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[str, str] | None:
        """
        Rule for passing project status on adjust_base behavior:
        We adjust the BASE of the comparison by removing from it lines that were removed in HEAD
        And then re-calculate BASE coverage and compare it to HEAD coverage.
        """
        log.info(
            "Applying adjust_base behavior to project status",
            extra=dict(commit=comparison.head.commit.commitid),
        )
        # If the user defined a target value for project coverage
        # Adjusting the base won't make HEAD change in relation to the target value
        # So we skip the calculation entirely
        if self.notifier_yaml_settings.get("target") not in ("auto", None):
            log.info(
                "Notifier settings specify target value. Skipping adjust_base.",
                extra=dict(commit=comparison.head.commit.commitid),
            )
            return None

        impacted_files = comparison.get_impacted_files().get("files", [])

        hits_removed = 0
        misses_removed = 0
        partials_removed = 0

        for file_dict in impacted_files:
            removed_diff_coverage_list = file_dict.get("removed_diff_coverage")
            if removed_diff_coverage_list:
                hits_removed += sum(
                    1 if item[1] == "h" else 0 for item in removed_diff_coverage_list
                )
                misses_removed += sum(
                    1 if item[1] == "m" else 0 for item in removed_diff_coverage_list
                )
                partials_removed += sum(
                    1 if item[1] == "p" else 0 for item in removed_diff_coverage_list
                )

        base_totals = comparison.project_coverage_base.report.totals
        base_adjusted_hits = base_totals.hits - hits_removed
        base_adjusted_misses = base_totals.misses - misses_removed
        base_adjusted_partials = base_totals.partials - partials_removed
        # The coverage info is in percentage, so multiply by 100
        base_adjusted_coverage = (
            Decimal(
                base_adjusted_hits
                / (base_adjusted_hits + base_adjusted_misses + base_adjusted_partials)
            )
            * 100
        )
        head_coverage = Decimal(comparison.head.report.totals.coverage)
        log.info(
            "Adjust base applied to project status",
            extra=dict(
                commit=comparison.head.commit.commitid,
                base_adjusted_coverage=base_adjusted_coverage,
                head_coverage=head_coverage,
                hits_removed=hits_removed,
                misses_removed=misses_removed,
                partials_removed=partials_removed,
            ),
        )
        # the head coverage is rounded to five digits after the dot, using shared.helpers.numeric.ratio
        # so we should round the base adjusted coverage to the same amount of digits after the dot
        # Decimal.quantize: https://docs.python.org/3/library/decimal.html#decimal.Decimal.quantize
        quantized_base_adjusted_coverage = base_adjusted_coverage.quantize(
            Decimal("0.00000")
        )
        if quantized_base_adjusted_coverage - head_coverage < Decimal("0.005"):
            rounded_difference = max(
                0,
                round_number(self.current_yaml, head_coverage - base_adjusted_coverage),
            )
            rounded_base_adjusted_coverage = round_number(
                self.current_yaml, base_adjusted_coverage
            )
            return (
                "success",
                f", passed because coverage increased by {rounded_difference}% when compared to adjusted base ({rounded_base_adjusted_coverage}%)",
            )
        return None

    def _apply_fully_covered_patch_behavior(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[str, str] | None:
        """
        Rule for passing project status on fully_covered_patch behavior:
        Pass if patch coverage is 100% and there are no unexpected changes
        """
        log.info(
            "Applying fully_covered_patch behavior to project status",
            extra=dict(commit=comparison.head.commit.commitid),
        )
        impacted_files = comparison.get_impacted_files().get("files", [])

        no_unexpected_changes = all(
            not file.get("unexpected_line_changes") for file in impacted_files
        )

        if not no_unexpected_changes:
            log.info(
                "Unexpected changes when applying patch_100 behavior",
                extra=dict(commit=comparison.head.commit.commitid),
            )
            return None

        diff = comparison.get_diff(use_original_base=True)
        patch_totals = comparison.head.report.apply_diff(diff)
        if patch_totals is None or patch_totals.lines == 0:
            # Coverage was not changed by patch
            return ("success", ", passed because coverage was not affected by patch")
        coverage = Decimal(patch_totals.coverage)
        if coverage == 100.0:
            return (
                "success",
                ", passed because patch was fully covered by tests, and no indirect coverage changes",
            )
        return None

    def get_project_status(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[str, str]:
        state, message = self._get_project_status(comparison)
        if state == "success":
            return (state, message)

        # Possibly pass the status check via removed_code_behavior
        # We need both reports to be able to get the diff and apply the removed_code behavior
        if comparison.project_coverage_base.report and comparison.head.report:
            removed_code_behavior = self.notifier_yaml_settings.get(
                "removed_code_behavior", self.DEFAULT_REMOVED_CODE_BEHAVIOR
            )
            # Apply removed_code_behavior
            removed_code_result = None
            if removed_code_behavior == "removals_only":
                removed_code_result = self._apply_removals_only_behavior(comparison)
            elif removed_code_behavior == "adjust_base":
                removed_code_result = self._apply_adjust_base_behavior(comparison)
            elif removed_code_behavior == "fully_covered_patch":
                removed_code_result = self._apply_fully_covered_patch_behavior(
                    comparison
                )
            else:
                if removed_code_behavior not in [False, "off"]:
                    log.warning(
                        "Unknown removed_code_behavior",
                        extra=dict(
                            removed_code_behavior=removed_code_behavior,
                            commit_id=comparison.head.commit.commitid,
                        ),
                    )
            # Possibly change status
            if removed_code_result:
                removed_code_state, removed_code_message = removed_code_result
                return (removed_code_state, message + removed_code_message)
        return (state, message)

    def _get_project_status(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[str, str]:
        if comparison.head.report.totals.coverage is None:
            state = self.notifier_yaml_settings.get("if_not_found", "success")
            message = "No coverage information found on head"
            return (state, message)

        threshold = Decimal(self.notifier_yaml_settings.get("threshold") or "0.0")
        head_coverage = Decimal(comparison.head.report.totals.coverage)
        head_coverage_rounded = round_number(self.current_yaml, head_coverage)

        if self.notifier_yaml_settings.get("target") not in ("auto", None):
            # Explicit target coverage defined in YAML
            target_coverage = Decimal(
                str(self.notifier_yaml_settings.get("target")).replace("%", "")
            )
            state = (
                "success"
                if ((head_coverage + threshold) >= target_coverage)
                else "failure"
            )
            expected_coverage_str = round_number(self.current_yaml, target_coverage)
            message = f"{head_coverage_rounded}% (target {expected_coverage_str}%)"
            return (state, message)
        if comparison.project_coverage_base.report is None:
            # No base report - can't pass by offset coverage
            state = self.notifier_yaml_settings.get("if_not_found", "success")
            message = "No report found to compare against"
            return (state, message)
        if comparison.project_coverage_base.report.totals.coverage is None:
            # Base report, no coverage on base report - can't pass by offset coverage
            state = self.notifier_yaml_settings.get("if_not_found", "success")
            message = "No coverage information found on base report"
            return (state, message)
        # Proper comparison head vs base report
        target_coverage = Decimal(
            comparison.project_coverage_base.report.totals.coverage
        )
        state = "success" if head_coverage + threshold >= target_coverage else "failure"
        change_coverage = round_number(
            self.current_yaml, head_coverage - target_coverage
        )
        message = f"{head_coverage_rounded}% ({change_coverage:+}%) compared to {comparison.project_coverage_base.commit.commitid[:7]}"
        return (state, message)
