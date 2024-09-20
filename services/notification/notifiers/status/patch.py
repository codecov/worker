from database.enums import Notification
from services.notification.notifiers.base import Comparison
from services.notification.notifiers.mixins.status import StatusPatchMixin
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

    @property
    def notification_type(self) -> Notification:
        return Notification.status_patch

    def build_payload(self, comparison: Comparison):
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            return {"state": state, "message": message}

        state, message = self.get_patch_status(comparison)
        if self.should_use_upgrade_decoration():
            message = self.get_upgrade_message()

        return {"state": state, "message": message}
