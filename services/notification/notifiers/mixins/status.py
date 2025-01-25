import logging
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Literal, TypedDict

from services.comparison import ComparisonProxy, FilteredComparison
from services.yaml.reader import round_number

log = logging.getLogger(__name__)


class StatusState(Enum):
    success = "success"
    failure = "failure"


class StatusResult(TypedDict):
    """
    The mixins in this file do the calculations and decide the SuccessState for all Status and Checks Notifiers.
    Checks have different fields than Statuses, so Checks are converted to the CheckResult type later.
    """

    state: Literal["success", "failure"]  # StatusState values
    message: str
    included_helper_text: dict[str, str]


CUSTOM_TARGET_TEXT_PATCH_KEY = "custom_target_helper_text_patch"
CUSTOM_TARGET_TEXT_PROJECT_KEY = "custom_target_helper_text_project"
CUSTOM_TARGET_TEXT_VALUE = (
    "Your {context} {notification_type} has failed because the {point_of_comparison} coverage ({coverage}%) is below the target coverage ({target}%). "
    "You can increase the {point_of_comparison} coverage or adjust the "
    "[target](https://docs.codecov.com/docs/commit-status#target) coverage."
)


HELPER_TEXT_MAP = {
    CUSTOM_TARGET_TEXT_PATCH_KEY: CUSTOM_TARGET_TEXT_VALUE,
    CUSTOM_TARGET_TEXT_PROJECT_KEY: CUSTOM_TARGET_TEXT_VALUE,
}


class StatusPatchMixin(object):
    context = "patch"

    def _get_threshold(self) -> Decimal:
        """
        Threshold can be configured by user, default is 0.0
        """
        threshold = self.notifier_yaml_settings.get("threshold", "0.0")

        try:
            # check if user has erroneously added a % to this input and fix
            threshold = Decimal(str(threshold).replace("%", ""))
        except (InvalidOperation, TypeError, AttributeError):
            threshold = Decimal("0.0")
        return threshold

    def _get_target(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[Decimal | None, bool]:
        """
        Target can be configured by user, default is auto, which is the coverage level from the base report.
        Target will be None if no report is found to compare against.
        """
        if self.notifier_yaml_settings.get("target") not in ("auto", None):
            # check if user has erroneously added a % to this input and fix
            target_coverage = Decimal(
                str(self.notifier_yaml_settings.get("target")).replace("%", "")
            )
            is_custom_target = True
        else:
            target_coverage = (
                Decimal(comparison.project_coverage_base.report.totals.coverage)
                if comparison.has_project_coverage_base_report()
                and comparison.project_coverage_base.report.totals.coverage is not None
                else None
            )
            is_custom_target = False
        return target_coverage, is_custom_target

    def get_patch_status(
        self, comparison: ComparisonProxy | FilteredComparison, notification_type: str
    ) -> StatusResult:
        threshold = self._get_threshold()
        target_coverage, is_custom_target = self._get_target(comparison)
        totals = comparison.get_patch_totals()
        included_helper_text = {}

        # coverage affected
        if totals and totals.lines > 0:
            coverage = Decimal(totals.coverage)
            if target_coverage is None:
                state = self.notifier_yaml_settings.get(
                    "if_not_found", StatusState.success.value
                )
                message = "No report found to compare against"
            else:
                state = (
                    StatusState.success.value
                    if coverage >= target_coverage
                    else StatusState.failure.value
                )
                # use rounded numbers for messages
                coverage_rounded = round_number(self.current_yaml, coverage)
                target_rounded = round_number(self.current_yaml, target_coverage)
                if state == StatusState.failure.value and coverage >= (
                    target_coverage - threshold
                ):
                    threshold_rounded = round_number(self.current_yaml, threshold)
                    state = StatusState.success.value
                    message = f"{coverage_rounded}% of diff hit (within {threshold_rounded}% threshold of {target_rounded}%)"
                else:
                    message = (
                        f"{coverage_rounded}% of diff hit (target {target_rounded}%)"
                    )
                if state == StatusState.failure.value and is_custom_target:
                    helper_text = HELPER_TEXT_MAP[CUSTOM_TARGET_TEXT_PATCH_KEY].format(
                        context=self.context,
                        notification_type=notification_type,
                        point_of_comparison=self.context,
                        coverage=coverage_rounded,
                        target=target_rounded,
                    )
                    included_helper_text[CUSTOM_TARGET_TEXT_PATCH_KEY] = helper_text
            return StatusResult(
                state=state, message=message, included_helper_text=included_helper_text
            )

        # coverage not affected
        if comparison.project_coverage_base.commit:
            description = "Coverage not affected when comparing {0}...{1}".format(
                comparison.project_coverage_base.commit.commitid[:7],
                comparison.head.commit.commitid[:7],
            )
        else:
            description = "Coverage not affected"
        return StatusResult(
            state=StatusState.success.value,
            message=description,
            included_helper_text=included_helper_text,
        )


class StatusChangesMixin(object):
    context = "changes"

    def is_a_change_worth_noting(self, change) -> bool:
        if not change.new and not change.deleted:
            # has totals and not -10m => 10h
            t = change.totals
            if t:
                # new missed||partial lines
                return (t.misses + t.partials) > 0
        return False

    def get_changes_status(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> tuple[str, str]:
        pull = comparison.pull
        if self.notifier_yaml_settings.get("base") in ("auto", None, "pr") and pull:
            if not comparison.has_project_coverage_base_report():
                description = (
                    "Unable to determine changes, no report found at pull request base"
                )
                state = StatusState.success.value
                return state, description

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
                StatusState.success.value
                if self.notifier_yaml_settings.get("informational")
                else StatusState.failure.value
            )
            return state, description

        description = "No indirect coverage changes found"
        return StatusState.success.value, description


class StatusProjectMixin(object):
    DEFAULT_REMOVED_CODE_BEHAVIOR = "adjust_base"
    context = "project"
    point_of_comparison = "head"

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
            return (
                StatusState.success.value,
                ", passed because this change only removed code",
            )
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
        base_adjusted_totals = (
            base_adjusted_hits + base_adjusted_misses + base_adjusted_partials
        )

        if not base_adjusted_totals:
            return None

        # The coverage info is in percentage, so multiply by 100
        base_adjusted_coverage = (
            Decimal(base_adjusted_hits / base_adjusted_totals) * 100
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
                StatusState.success.value,
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
            return (
                StatusState.success.value,
                ", passed because coverage was not affected by patch",
            )
        coverage = Decimal(patch_totals.coverage)
        if coverage == 100.0:
            return (
                StatusState.success.value,
                ", passed because patch was fully covered by tests, and no indirect coverage changes",
            )
        return None

    def get_project_status(
        self, comparison: ComparisonProxy | FilteredComparison, notification_type: str
    ) -> StatusResult:
        result = self._get_project_status(
            comparison, notification_type=notification_type
        )
        if result["state"] == StatusState.success.value:
            return result

        # Possibly pass the status check via removed_code_behavior
        # The removed code behavior can change the `state` from `failure` to `success` and add to the `message`.
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
                if removed_code_state == StatusState.success.value:
                    # the status was failure, has been changed to success through RCB settings
                    # since the status is no longer failing, remove any included_helper_text
                    result["included_helper_text"] = {}
                result["state"] = removed_code_state
                result["message"] = result["message"] + removed_code_message
        return result

    def _get_threshold(self) -> Decimal:
        """
        Threshold can be configured by user, default is 0.0
        """
        threshold = self.notifier_yaml_settings.get("threshold", "0.0")

        try:
            # check if user has erroneously added a % to this input and fix
            threshold = Decimal(str(threshold).replace("%", ""))
        except (InvalidOperation, TypeError, AttributeError):
            threshold = Decimal("0.0")
        return threshold

    def _get_target(
        self, base_report_totals: ComparisonProxy | FilteredComparison
    ) -> tuple[Decimal, bool]:
        """
        Target can be configured by user, default is auto, which is the coverage level from the base report.
        """
        if self.notifier_yaml_settings.get("target") not in ("auto", None):
            # check if user has erroneously added a % to this input and fix
            target_coverage = Decimal(
                str(self.notifier_yaml_settings.get("target")).replace("%", "")
            )
            is_custom_target = True
        else:
            target_coverage = Decimal(base_report_totals.coverage)
            is_custom_target = False
        return target_coverage, is_custom_target

    def _get_project_status(
        self, comparison: ComparisonProxy | FilteredComparison, notification_type: str
    ) -> StatusResult:
        included_helper_text = {}
        if (
            not comparison.head.report
            or (head_report_totals := comparison.head.report.totals) is None
            or head_report_totals.coverage is None
        ):
            state = self.notifier_yaml_settings.get(
                "if_not_found", StatusState.success.value
            )
            message = "No coverage information found on head"
            return StatusResult(
                state=state, message=message, included_helper_text=included_helper_text
            )

        base_report = comparison.project_coverage_base.report
        if base_report is None:
            # No base report - can't pass by offset coverage
            state = self.notifier_yaml_settings.get(
                "if_not_found", StatusState.success.value
            )
            message = "No report found to compare against"
            return StatusResult(
                state=state, message=message, included_helper_text=included_helper_text
            )

        base_report_totals = base_report.totals
        if base_report_totals.coverage is None:
            # Base report, no coverage on base report - can't pass by offset coverage
            state = self.notifier_yaml_settings.get(
                "if_not_found", StatusState.success.value
            )
            message = "No coverage information found on base report"
            return StatusResult(
                state=state, message=message, included_helper_text=included_helper_text
            )

        # Proper comparison head vs base report
        threshold = self._get_threshold()
        target_coverage, is_custom_target = self._get_target(base_report_totals)
        head_coverage = Decimal(head_report_totals.coverage)
        head_coverage_rounded = round_number(self.current_yaml, head_coverage)

        # threshold is used to determine success/failure, but is not included in messaging
        state = (
            StatusState.success.value
            if head_coverage >= (target_coverage - threshold)
            else StatusState.failure.value
        )

        if is_custom_target:
            # Explicit target coverage defined in YAML
            # use rounded numbers for messages
            target_rounded = round_number(self.current_yaml, target_coverage)
            message = f"{head_coverage_rounded}% (target {target_rounded}%)"
            if state == StatusState.failure.value:
                helper_text = HELPER_TEXT_MAP[CUSTOM_TARGET_TEXT_PROJECT_KEY].format(
                    context=self.context,
                    notification_type=notification_type,
                    point_of_comparison=self.point_of_comparison,
                    coverage=head_coverage_rounded,
                    target=target_rounded,
                )
                included_helper_text[CUSTOM_TARGET_TEXT_PROJECT_KEY] = helper_text
            return StatusResult(
                state=state, message=message, included_helper_text=included_helper_text
            )

        # use rounded numbers for messages
        change_coverage_rounded = round_number(
            self.current_yaml, head_coverage - target_coverage
        )
        message = f"{head_coverage_rounded}% ({change_coverage_rounded:+}%) compared to {comparison.project_coverage_base.commit.commitid[:7]}"
        return StatusResult(
            state=state, message=message, included_helper_text=included_helper_text
        )
