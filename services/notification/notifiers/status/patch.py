from database.enums import Notification
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.mixins.status import StatusPatchMixin, StatusResult
from services.notification.notifiers.status.base import StatusNotifier


class PatchStatusNotifier(StatusPatchMixin, StatusNotifier):
    """This status analyzes the git patch and sees covered lines within it

    Attributes:
        context (str): The context

    Possible results
        - No report found to compare against
        - f'{coverage_str}% of diff hit (within {threshold_str}% threshold of {target_str}%)'
        - {coverage_str}% of diff hit (target {target_str}%)
    """

    context = "patch"
    notification_type_display_name = "status"

    @property
    def notification_type(self) -> Notification:
        return Notification.status_patch

    def build_payload(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> StatusResult:
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            result = StatusResult(state=state, message=message, included_helper_text={})
            return result

        result = self.get_patch_status(
            comparison, notification_type=self.notification_type_display_name
        )
        if self.should_use_upgrade_decoration():
            result["message"] = self.get_upgrade_message()

        return result
