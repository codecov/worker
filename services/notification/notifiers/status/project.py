import logging

from database.enums import Notification
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.mixins.status import (
    StatusProjectMixin,
    StatusResult,
)
from services.notification.notifiers.status.base import StatusNotifier

log = logging.getLogger(__name__)


class ProjectStatusNotifier(StatusProjectMixin, StatusNotifier):
    """

    Attributes:
        context (str): The context

    Possible results
        - 100% remains the same compared to 29320f9
        - 57.42% (+<.01%) compared to 559fe9e
        - 85.65% (target 87%)
        - No report found to compare against

    Not implemented results (yet):
        - Absolute coverage decreased by -{0}% but relative coverage ...
    """

    context = "project"
    notification_type_display_name = "status"

    @property
    def notification_type(self) -> Notification:
        return Notification.status_project

    def build_payload(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> StatusResult:
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            return StatusResult(state=state, message=message, included_helper_text={})

        result = self.get_project_status(
            comparison, notification_type=self.notification_type_display_name
        )
        if self.should_use_upgrade_decoration():
            result["message"] = self.get_upgrade_message()
        return result
