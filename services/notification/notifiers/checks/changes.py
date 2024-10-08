from database.enums import Notification
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.checks.base import ChecksNotifier
from services.notification.notifiers.mixins.status import StatusChangesMixin


class ChangesChecksNotifier(StatusChangesMixin, ChecksNotifier):
    context = "changes"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_changes

    def build_payload(self, comparison: ComparisonProxy | FilteredComparison) -> dict:
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            return {
                "state": state,
                "output": {
                    "title": "Empty Upload",
                    "summary": message,
                },
            }
        state, message = self.get_changes_status(comparison)
        codecov_link = self.get_codecov_pr_link(comparison)

        title = message

        should_use_upgrade = self.should_use_upgrade_decoration()
        if should_use_upgrade:
            message = self.get_upgrade_message(comparison)
            title = "Codecov Report"

        return {
            "state": state,
            "output": {
                "title": f"{title}",
                "summary": "\n\n".join([codecov_link, message]),
            },
        }
