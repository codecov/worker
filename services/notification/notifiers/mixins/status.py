import logging
from decimal import Decimal
from typing import Optional, Tuple, Union

from services.comparison import ComparisonProxy, FilteredComparison
from services.yaml.reader import round_number

log = logging.getLogger(__name__)


class StatusPatchMixin(object):
    async def get_patch_status(self, comparison) -> Tuple[str, str]:
        threshold = Decimal(self.notifier_yaml_settings.get("threshold") or "0.0")
        diff = await self.get_diff(comparison)
        totals = comparison.head.report.apply_diff(diff)
        if self.notifier_yaml_settings.get("target") not in ("auto", None):
            target_coverage = Decimal(
                str(self.notifier_yaml_settings.get("target")).replace("%", "")
            )
        else:
            target_coverage = (
                Decimal(comparison.base.report.totals.coverage)
                if comparison.has_base_report()
                and comparison.base.report.totals.coverage is not None
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
        if comparison.base.commit:
            description = "Coverage not affected when comparing {0}...{1}".format(
                comparison.base.commit.commitid[:7], comparison.head.commit.commitid[:7]
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

    async def get_changes_status(self, comparison) -> Tuple[str, str]:
        pull = comparison.pull
        if self.notifier_yaml_settings.get("base") in ("auto", None, "pr") and pull:
            if not comparison.has_base_report():
                description = (
                    "Unable to determine changes, no report found at pull request base"
                )
                state = "success"
                return (state, description)

        # filter changes
        changes = await comparison.get_changes()
        if changes:
            changes = list(filter(self.is_a_change_worth_noting, changes))

        # remove new additions
        if changes:
            lpc = len(changes)
            eng = "files have" if lpc > 1 else "file has"
            description = (
                "{0} {1} unexpected coverage changes not visible in diff".format(
                    lpc, eng
                )
            )
            state = (
                "success"
                if self.notifier_yaml_settings.get("informational")
                else "failure"
            )
            return (state, description)

        description = "No unexpected coverage changes found"
        return ("success", description)


class StatusProjectMixin(object):

    # TODO: The actual default should be "patch" but it's not implemented yet
    DEFAULT_REMOVED_CODE_BEHAVIOR = "off"

    async def _apply_removals_only_behavior(
        self, comparison: Union[ComparisonProxy, FilteredComparison]
    ) -> Optional[Tuple[str, str]]:
        """
        Rule for passing project status on removals_only behavior:
        Pass if code was _only removed_ (i.e. no addition, no unexpected changes)
        """
        impacted_files_dict = await comparison.get_impacted_files()
        impacted_files = impacted_files_dict.get("files", [])
        no_added_no_unexpected_change = all(
            map(
                lambda file_dict: (
                    file_dict.get("added_diff_coverage", []) == []
                    and file_dict.get("unexpected_line_changes") == []
                ),
                impacted_files,
            )
        )
        some_removed = any(
            map(
                lambda file_dict: (file_dict.get("removed_diff_coverage", []) != []),
                impacted_files,
            )
        )
        if no_added_no_unexpected_change and some_removed:
            return ("success", f", passed because this change only removed code")
        return None

    async def get_project_status(
        self, comparison: Union[ComparisonProxy, FilteredComparison]
    ) -> Tuple[str, str]:
        state, message = self._get_project_status(comparison)
        if state == "success":
            return (state, message)

        # Possibly pass the status check via removed_code_behavior
        # We need both reports to be able to get the diff and apply the removed_code behavior
        if comparison.base.report and comparison.head.report:
            removed_code_behavior = self.notifier_yaml_settings.get(
                "removed_code_behavior", self.DEFAULT_REMOVED_CODE_BEHAVIOR
            )
            # Apply removed_code_behavior
            removed_code_result = None
            if removed_code_behavior == "removals_only":
                removed_code_result = await self._apply_removals_only_behavior(
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

    def _get_project_status(self, comparison) -> Tuple[str, str]:
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
        if comparison.base.report is None:
            # No base report - can't pass by offset coverage
            state = self.notifier_yaml_settings.get("if_not_found", "success")
            message = "No report found to compare against"
            return (state, message)
        if comparison.base.report.totals.coverage is None:
            # Base report, no coverage on base report - can't pass by offset coverage
            state = self.notifier_yaml_settings.get("if_not_found", "success")
            message = "No coverage information found on base report"
            return (state, message)
        # Proper comparison head vs base report
        target_coverage = Decimal(comparison.base.report.totals.coverage)
        state = "success" if head_coverage + threshold >= target_coverage else "failure"
        change_coverage = round_number(
            self.current_yaml, head_coverage - target_coverage
        )
        message = f"{head_coverage_rounded}% ({change_coverage:+}%) compared to {comparison.base.commit.commitid[:7]}"
        return (state, message)
