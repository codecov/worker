import logging
from typing import NamedTuple, Never

import sentry_sdk
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME, Commit, Owner
from services.bundle_analysis.notify.contexts import (
    BaseBundleAnalysisNotificationContext,
    NotificationContextBuilder,
    NotificationContextBuildError,
)
from services.bundle_analysis.notify.contexts.comment import (
    BundleAnalysisPRCommentContextBuilder,
)
from services.bundle_analysis.notify.contexts.commit_status import (
    CommitStatusNotificationContextBuilder,
)
from services.bundle_analysis.notify.helpers import get_notification_types_configured
from services.bundle_analysis.notify.messages import MessageStrategyInterface
from services.bundle_analysis.notify.messages.comment import (
    BundleAnalysisCommentMarkdownStrategy,
)
from services.bundle_analysis.notify.messages.commit_status import (
    CommitStatusMessageStrategy,
)
from services.bundle_analysis.notify.types import NotificationSuccess, NotificationType

log = logging.getLogger(__name__)


class NotificationFullContext(NamedTuple):
    notification_context: BaseBundleAnalysisNotificationContext
    message_strategy: MessageStrategyInterface


class BundleAnalysisNotifyReturn(NamedTuple):
    notifications_configured: tuple[NotificationType, ...]
    notifications_attempted: tuple[NotificationType, ...] | tuple[Never]
    notifications_successful: tuple[NotificationType, ...] | tuple[Never]

    def to_NotificationSuccess(self) -> NotificationSuccess:
        notification_configured_count = len(self.notifications_configured)
        notifications_successful_count = len(self.notifications_successful)
        if notification_configured_count == 0:
            return NotificationSuccess.NOTHING_TO_NOTIFY
        if notification_configured_count == notifications_successful_count:
            return NotificationSuccess.FULL_SUCCESS
        return NotificationSuccess.PARTIAL_SUCCESS


class BundleAnalysisNotifyService:
    def __init__(
        self,
        commit: Commit,
        current_yaml: UserYaml,
        gh_app_installation_name: str | None = None,
    ):
        self.commit = commit
        self.current_yaml = current_yaml
        self.gh_app_installation_name = (
            gh_app_installation_name or GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )

    @property
    def owner(self) -> Owner:
        return self.commit.repository.owner

    @sentry_sdk.trace
    def build_base_context(self) -> BaseBundleAnalysisNotificationContext | None:
        try:
            return (
                NotificationContextBuilder()
                .initialize(
                    self.commit, self.current_yaml, self.gh_app_installation_name
                )
                .build_context()
                .get_result()
            )
        except NotificationContextBuildError as exp:
            log.warning(
                "Failed to build NotificationContext",
                extra=dict(
                    notification_type="base_context", failed_step=exp.failed_step
                ),
            )
        return None

    def create_context_for_notification(
        self,
        base_context: BaseBundleAnalysisNotificationContext,
        notification_type: NotificationType,
    ) -> NotificationFullContext | None:
        """Builds the NotificationContext for the given notification_type
        If the NotificationContext failed to build we can't send this notification.

        Each NotificationType is paired with a ContextBuilder and MessageStrategyInterface.
        The MessageStrategy is later used to build and send the message based on the NotificationContext
        """
        notifier_lookup: dict[
            NotificationType,
            tuple[NotificationContextBuilder, MessageStrategyInterface],
        ] = {
            NotificationType.PR_COMMENT: (
                BundleAnalysisPRCommentContextBuilder(),
                BundleAnalysisCommentMarkdownStrategy(),
            ),
            NotificationType.COMMIT_STATUS: (
                CommitStatusNotificationContextBuilder(),
                CommitStatusMessageStrategy(),
            ),
            # The commit-check API is more powerful than COMMIT_STATUS
            # but we currently don't differentiate between them
            NotificationType.GITHUB_COMMIT_CHECK: (
                CommitStatusNotificationContextBuilder(),
                CommitStatusMessageStrategy(),
            ),
        }
        notifier_strategy = notifier_lookup.get(notification_type)
        if notifier_strategy is None:
            msg = f"No context builder for {notification_type}. Skipping"
            log.error(msg)
            return None
        builder_instance, message_strategy_instance = notifier_strategy
        try:
            builder = builder_instance.initialize_from_context(
                self.current_yaml, base_context
            )
            return NotificationFullContext(
                builder.build_context().get_result(),
                message_strategy_instance,
            )
        except NotificationContextBuildError as exp:
            log.warning(
                "Failed to build NotificationContext",
                extra=dict(
                    notification_type=notification_type, failed_step=exp.failed_step
                ),
            )
            return None

    def get_notification_contexts(
        self,
        base_context: BaseBundleAnalysisNotificationContext,
        notification_types: tuple[NotificationType, ...],
    ) -> list[NotificationFullContext]:
        previous_context = base_context
        specific_contexts = []
        for notification_type in notification_types:
            full_context = self.create_context_for_notification(
                previous_context, notification_type
            )
            if full_context:
                previous_context = full_context.notification_context
                specific_contexts.append(full_context)
        return specific_contexts

    def notify(self) -> BundleAnalysisNotifyReturn:
        """Entrypoint for BundleAnalysis notifications. This function does the following:
            1. Gets the configured notifications. Those are the ones we must send;
            2. Attempts to build a BaseContext with necessary info for all notifications;
            3. Attempts to build a Context for each notification to be sent;
            4. For each notification with a context, build and send the message.

        Returns: BundleAnalysisNotifyReturn - tuple with notifications configured and the ones
            that we successfully notified.
        """
        notification_types = get_notification_types_configured(
            self.current_yaml, self.owner
        )
        base_context = self.build_base_context()
        if base_context is None:
            log.warning("Skipping ALL notifications because there's no base context")
            return BundleAnalysisNotifyReturn(
                notifications_configured=notification_types,
                notifications_attempted=tuple(),
                notifications_successful=tuple(),
            )

        notification_full_contexts = self.get_notification_contexts(
            base_context, notification_types
        )
        notifications_sent = []
        notifications_successful = []
        for notification_context, message_strategy in notification_full_contexts:
            message = message_strategy.build_message(notification_context)
            result = message_strategy.send_message(notification_context, message)
            if result.notification_attempted:
                notifications_sent.append(notification_context.notification_type)
            if result.notification_successful:
                notifications_successful.append(notification_context.notification_type)
            log.info(
                "Notification done",
                extra=dict(
                    notification_type=notification_context.notification_type,
                    notification_result=result,
                ),
            )

        return BundleAnalysisNotifyReturn(
            notifications_configured=notification_types,
            notifications_attempted=tuple(notifications_sent),
            notifications_successful=tuple(notifications_successful),
        )
