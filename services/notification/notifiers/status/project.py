import logging
from decimal import Decimal

from database.enums import Notification
from services.notification.notifiers.base import Comparison
from services.notification.notifiers.status.base import StatusNotifier
from services.yaml.reader import round_number
from typing import Any, Tuple

log = logging.getLogger(__name__)


class ProjectStatusNotifier(StatusNotifier):

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

    def _get_project_status(self, comparison) -> Tuple[str, str]:
        threshold = Decimal(self.notifier_yaml_settings.get("threshold") or "0.0")
        if self.notifier_yaml_settings.get("target") not in ("auto", None):
            head_coverage = Decimal(comparison.head.report.totals.coverage)
            target_coverage = Decimal(
                str(self.notifier_yaml_settings.get("target")).replace("%", "")
            )
            state = (
                "success"
                if ((head_coverage + threshold) >= target_coverage)
                else "failure"
            )
            head_coverage_str = round_number(self.current_yaml, head_coverage)
            expected_coverage_str = round_number(self.current_yaml, target_coverage)
            message = f"{head_coverage_str}% (target {expected_coverage_str}%)"
            return (state, message)
        if comparison.base.report is None:
            state = self.notifier_yaml_settings.get("if_not_found", "success")
            message = "No report found to compare against"
            return (state, message)
        target_coverage = Decimal(comparison.base.report.totals.coverage)
        head_coverage = Decimal(comparison.head.report.totals.coverage)
        head_coverage_rounded = round_number(self.current_yaml, head_coverage)
        if head_coverage == target_coverage:
            state = "success"
            message = f"{head_coverage_rounded}% remains the same compared to {comparison.base.commit.commitid[:7]}"
        state = "success" if head_coverage + threshold >= target_coverage else "failure"
        change_coverage = round_number(
            self.current_yaml, head_coverage - target_coverage
        )
        message = f"{head_coverage_rounded}% (+{change_coverage}%) compared to {comparison.base.commit.commitid[:7]}"
        return (state, message)

    async def build_payload(self, comparison: Comparison):
        state, message = self._get_project_status(comparison)
        if self.should_use_upgrade_decoration():
            message = self.get_upgrade_message()
        return {
            "state": state,
            "message": message,
        }
