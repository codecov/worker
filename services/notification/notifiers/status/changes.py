import logging
from services.notification.notifiers.mixins.status import StatusChangesMixin
from services.notification.notifiers.status.base import StatusNotifier
from typing import Any, Dict, Tuple

log = logging.getLogger(__name__)


class ChangesStatusNotifier(StatusChangesMixin, StatusNotifier):

    """This status analyzes the "unexpected changes" (see services/notification/changes.py
        for a better description) and covered lines within it

    Attributes:
        context (str): The context

    Possible results
        - 'No unexpected coverage changes found.'
        - {0} {1} unexpected coverage changes not visible in diff
        - Unable to determine changes, no report found at pull request base
    """

    context = "changes"

    async def build_payload(self, comparison) -> Dict[str, str]:
        state, message = await self.get_changes_status(comparison)
        if self.should_use_upgrade_decoration():
            message = self.get_upgrade_message()

        return {"state": state, "message": message}
