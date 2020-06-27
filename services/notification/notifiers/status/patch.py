from database.enums import Notification
from services.notification.notifiers.base import Comparison
from services.notification.notifiers.status.base import StatusNotifier
from services.notification.notifiers.mixins.status import StatusPatchMixin


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

    async def build_payload(self, comparison: Comparison):
        state, message = await self.get_patch_status(comparison)
        if self.should_use_upgrade_decoration():
            message = self.get_upgrade_message()

        return {"state": state, "message": message}
