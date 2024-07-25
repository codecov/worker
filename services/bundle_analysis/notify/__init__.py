import logging
from typing import NamedTuple

from asgiref.sync import async_to_sync
from shared.django_apps.codecov_auth.models import Service
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME, Commit
from services.bundle_analysis.notify.contexts import (
    BaseBundleAnalysisNotificationContext,
    NotificationContextBuilder,
    NotificationContextBuildError,
)
from services.bundle_analysis.notify.contexts.comment import (
    BundleAnalysisCommentContextBuilder,
)
from services.bundle_analysis.notify.helpers import get_notification_types_configured
from services.bundle_analysis.notify.messages import MessageStrategyInterface
from services.bundle_analysis.notify.messages.comment import (
    BundleAnalysisCommentMarkdownStrategy,
)
from services.bundle_analysis.notify.types import NotificationType

log = logging.getLogger(__name__)


class NotificationFullContext(NamedTuple):
    notification_context: BaseBundleAnalysisNotificationContext
    message_strategy: MessageStrategyInterface


def create_context_for_notification(
    notification_type: NotificationType,
) -> NotificationFullContext | None:
    """Builds the NotificationContext for the given notification_type
    If te NotificationContext failed to build we can't send this notification.
    """
    builders_lookup: dict[NotificationType, NotificationContextBuilder] = {
        NotificationType.PR_COMMENT: NotificationFullContext(
            BundleAnalysisCommentContextBuilder, BundleAnalysisCommentMarkdownStrategy
        )
    }
    builder_class, message_strategy_class = builders_lookup.get(notification_type)

    if builder_class is None:
        msg = f"No context builder for {notification_type.name}. Skipping"
        log.error(msg)
        return None
    try:
        return NotificationFullContext(
            builder_class.build_specialized_context(notification_type),
            message_strategy_class(),
        )
    except NotificationContextBuildError as exp:
        log.error(
            "Failed to build NotificationContext",
            extra=dict(
                notification_type=notification_type, failed_step=exp.failed_step
            ),
        )
        return None


class BundleAnalysisNotifyReturn(NamedTuple):
    notifications_configured: tuple[NotificationType]
    notifications_successful: tuple[NotificationType]


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
    def owner_service(self) -> Service:
        return Service(self.commit.repository.service)

    def notify(self) -> BundleAnalysisNotifyReturn:
        notification_types = get_notification_types_configured(
            self.current_yaml, self.owner_service
        )
        notification_full_contexts = filter(
            None, map(create_context_for_notification, notification_types)
        )
        notifications_sent = []
        for notification_context, message_strategy in notification_full_contexts:
            message = message_strategy.build_message(notification_context)
            result = async_to_sync(
                message_strategy.send_message(notification_context, message)
            )
            notifications_sent.append(notification_context.notification_type)
            log.info(
                "Notification done",
                extra=dict(
                    notification_type=notification_context.notification_type,
                    notification_result=result,
                ),
            )

        return BundleAnalysisNotifyReturn(
            notifications_configured=notification_types,
            notifications_successful=tuple(*notifications_sent),
        )
