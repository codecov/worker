import logging

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
from services.bundle_analysis.notify.types import NotificationType

log = logging.getLogger(__name__)


def create_context_for_notification(
    notification_type: NotificationType,
) -> BaseBundleAnalysisNotificationContext | None:
    """Builds the NotificationContext for the given notification_type
    If te NotificationContext failed to build we can't send this notification.
    """
    builders_lookup: dict[NotificationType, NotificationContextBuilder] = {
        NotificationType.PR_COMMENT: BundleAnalysisCommentContextBuilder
    }
    builder_class_to_use = builders_lookup.get(notification_type)
    if builder_class_to_use is None:
        msg = f"No context builder for {notification_type.name}"
        raise Exception(msg)
    try:
        return builder_class_to_use.build_specialized_context(notification_type)
    except NotificationContextBuildError as exp:
        log.warning(
            "Failed to build NotificationContext",
            extra=dict(
                notification_type=notification_type, failed_step=exp.failed_step
            ),
        )
        return None


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

    def notify(self):
        notification_types = get_notification_types_configured(
            self.current_yaml, self.owner_service
        )
        notification_contexts = filter(
            None, map(create_context_for_notification, notification_types)
        )
        # TODO: Call build message
        # TODO: Call send message
        # TODO: Return results
