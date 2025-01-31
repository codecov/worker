from database.enums import Notification
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.checks.base import (
    CheckOutput,
    CheckResult,
    ChecksNotifier,
)
from services.notification.notifiers.mixins.status import StatusPatchMixin
from services.yaml import read_yaml_field


class PatchChecksNotifier(StatusPatchMixin, ChecksNotifier):
    context = "patch"
    notification_type_display_name = "check"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_patch

    def build_payload(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> CheckResult:
        """
        This method build the paylod of the patch github checks.

        We only add annotaions to the top-level patch check of a project.
        We do not add annotations on checks that are used with paths/flags
        """
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            result = CheckResult(
                state=state,
                output=CheckOutput(
                    title="Empty Upload",
                    summary=message,
                    annotations=[],
                ),
                included_helper_text={},
            )
            return result
        status_result = self.get_patch_status(
            comparison, notification_type=self.notification_type_display_name
        )
        codecov_link = self.get_codecov_pr_link(comparison)

        title = status_result["message"]
        message = status_result["message"]

        should_use_upgrade = self.should_use_upgrade_decoration()
        if should_use_upgrade:
            message = self.get_upgrade_message(comparison)
            title = "Codecov Report"

        checks_yaml_field = read_yaml_field(self.current_yaml, ("github_checks",))
        try:
            # checks_yaml_field can be dict, bool, None
            # should_annotate defaults to False as of Jan 30 2025
            should_annotate = checks_yaml_field.get("annotations", False)
        except AttributeError:
            should_annotate = False

        flags = self.notifier_yaml_settings.get("flags")
        paths = self.notifier_yaml_settings.get("paths")
        if (
            flags is not None
            or paths is not None
            or should_use_upgrade
            or should_annotate is False
        ):
            result = CheckResult(
                state=status_result["state"],
                output=CheckOutput(
                    title=title,
                    summary="\n\n".join([codecov_link, message]),
                    annotations=[],
                ),
                included_helper_text=status_result["included_helper_text"],
            )
            return result
        diff = comparison.get_diff(use_original_base=True)
        #  TODO: Look into why the apply diff in get_patch_status is not saving state at this point
        comparison.head.report.apply_diff(diff)
        annotations = self.create_annotations(comparison, diff)
        result = CheckResult(
            state=status_result["state"],
            output=CheckOutput(
                title=title,
                summary="\n\n".join([codecov_link, message]),
                annotations=annotations,
            ),
            included_helper_text=status_result["included_helper_text"],
        )
        return result
