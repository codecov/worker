from typing import Any, Dict, Tuple

from database.enums import Notification
from services.notification.notifiers.checks.base import ChecksNotifier
from services.notification.notifiers.mixins.status import StatusChangesMixin


class ChangesChecksNotifier(StatusChangesMixin, ChecksNotifier):
    context = "changes"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_changes

    async def build_payload(self, comparison) -> Dict[str, str]:
        state, message = await self.get_changes_status(comparison)
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
