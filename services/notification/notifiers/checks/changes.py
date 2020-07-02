from services.notification.notifiers.checks.base import ChecksNotifier
from services.notification.notifiers.mixins.status import StatusChangesMixin
from typing import Any, Dict, Tuple


class ChangesChecksNotifier(StatusChangesMixin, ChecksNotifier):
    context = "changes"

    async def build_payload(self, comparison) -> Dict[str, str]:
        state, message = await self.get_changes_status(comparison)
        codecov_link = self.get_codecov_pr_link(comparison)
        return {
            "state": state,
            "output": {
                "title": "Codecov Report",
                "summary": "\n\n".join([codecov_link, message]),
            },
        }
