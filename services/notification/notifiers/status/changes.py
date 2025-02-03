import logging

from database.enums import Notification
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.mixins.status import (
    StatusChangesMixin,
    StatusResult,
)
from services.notification.notifiers.status.base import StatusNotifier

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
    notification_type_display_name = "status"

    @property
    def notification_type(self) -> Notification:
        return Notification.status_changes

    def build_payload(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> StatusResult:
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            return StatusResult(state=state, message=message, included_helper_text={})
        result = self.get_changes_status(
            comparison, notification_type=self.notification_type_display_name
        )
        if self.should_use_upgrade_decoration():
            result["message"] = self.get_upgrade_message()

        return result
