import logging
from abc import ABC, abstractmethod

from shared.torngit.exceptions import (
    TorngitClientError,
)

from services.comparison import ComparisonProxy
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)

log = logging.getLogger(__name__)


class NotifyCondition(ABC):
    """Abstract class that defines the basis of a NotifyCondition.

    NotifyCondition specifies the conditions that need to be met in order for a notification to be sent
    from Codecov to a git provider.
    NotifyCondition can have a side effect that is called when the condition fails.
    """

    is_async_condition: bool = False
    failure_explanation: str

    @abstractmethod
    def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        return True

    def on_failure_side_effect(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> NotificationResult:
        return NotificationResult()


class AsyncNotifyCondition(NotifyCondition):
    """Async version of NotifyCondition"""

    is_async_condition: bool = True

    @abstractmethod
    async def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        return True

    async def on_failure_side_effect(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> NotificationResult:
        return NotificationResult()


class ComparisonHasPull(NotifyCondition):
    failure_explanation = "no_pull_request"

    def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        return comparison.pull is not None


class PullRequestInProvider(NotifyCondition):
    failure_explanation = "pull_request_not_in_provider"

    def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        return (
            comparison.enriched_pull is not None
            and comparison.enriched_pull.provider_pull is not None
        )


class PullRequestOpen(NotifyCondition):
    failure_explanation = "pull_request_closed"

    def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        return comparison.pull.state == "open"


class PullHeadMatchesComparisonHead(NotifyCondition):
    failure_explanation = "pull_head_does_not_match"

    def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        return comparison.pull.head == comparison.head.commit.commitid


class HasEnoughBuilds(NotifyCondition):
    failure_explanation = "not_enough_builds"

    def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        expected_builds = notifier.notifier_yaml_settings.get("after_n_builds", 0)
        present_builds = len(comparison.head.report.sessions)
        return present_builds >= expected_builds


class HasEnoughRequiredChanges(AsyncNotifyCondition):
    failure_explanation = "changes_required"

    async def check_condition(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> bool:
        requires_changes = notifier.notifier_yaml_settings.get("require_changes", False)
        return (requires_changes == False) or await notifier.has_enough_changes(
            comparison
        )

    async def on_failure_side_effect(
        notifier: AbstractBaseNotifier, comparison: ComparisonProxy
    ) -> NotificationResult:
        pull = comparison.pull
        data_received = None
        extra_log_info = dict(
            repoid=pull.repoid,
            pullid=pull.pullid,
            commentid=pull.commentid,
        )
        if pull.commentid is not None:
            # Just porting logic as-is, but not sure if it's the best
            # TODO: codecov/engineering-team#1761
            log.info(
                "Deleting comment because there are not enough changes according to YAML",
                extra=extra_log_info,
            )
            try:
                await notifier.repository_service.delete_comment(
                    pull.pullid, pull.commentid
                )
                data_received = {"deleted_comment": True}
            except TorngitClientError:
                log.warning(
                    "Comment could not be deleted due to client permissions",
                    exc_info=True,
                    extra=extra_log_info,
                )
                data_received = {"deleted_comment": False}
        return NotificationResult(data_received=data_received)
