import logging

from database.enums import Notification
from services.notification.notifiers.base import Comparison
from services.notification.notifiers.mixins.status import StatusProjectMixin
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

    @property
    def notification_type(self) -> Notification:
        return Notification.status_project

    def build_payload(self, comparison: Comparison):
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            return {"state": state, "message": message}

        state, message = self.get_project_status(comparison)
        if self.should_use_upgrade_decoration():
            message = self.get_upgrade_message()
        return {"state": state, "message": message}
