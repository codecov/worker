from database.enums import Notification
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.checks.base import (
    CheckOutput,
    CheckResult,
    ChecksNotifier,
)
from services.notification.notifiers.mixins.status import StatusChangesMixin


class ChangesChecksNotifier(StatusChangesMixin, ChecksNotifier):
    context = "changes"
    notification_type_display_name = "check"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_changes

    def build_payload(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> CheckResult:
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            return CheckResult(
                state=state,
                output=CheckOutput(
                    title="Empty Upload",
                    summary=message,
                    annotations=[],
                ),
                included_helper_text={},
            )

        status_result = self.get_changes_status(
            comparison, notification_type=self.notification_type_display_name
        )
        codecov_link = self.get_codecov_pr_link(comparison)

        title = status_result["message"]
        message = status_result["message"]

        should_use_upgrade = self.should_use_upgrade_decoration()
        if should_use_upgrade:
            message = self.get_upgrade_message(comparison)
            title = "Codecov Report"

        return CheckResult(
            state=status_result["state"],
            output=CheckOutput(
                title=title,
                summary="\n\n".join([codecov_link, message]),
                annotations=[],
            ),
            included_helper_text={},
        )
