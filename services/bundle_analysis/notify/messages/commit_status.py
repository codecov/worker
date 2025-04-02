import logging
from typing import TypedDict

import sentry_sdk
from asgiref.sync import async_to_sync
from django.template import loader
from shared.helpers.cache import make_hash_sha256
from shared.torngit.exceptions import TorngitClientError

from helpers.cache import cache
from services.bundle_analysis.notify.contexts.commit_status import (
    CommitStatusLevel,
    CommitStatusNotificationContext,
)
from services.bundle_analysis.notify.helpers import bytes_readable, get_github_app_used
from services.bundle_analysis.notify.messages import MessageStrategyInterface
from services.notification.notifiers.base import NotificationResult

log = logging.getLogger(__name__)


class BundleCommentTemplateContext(TypedDict):
    prefix_message: str
    change_readable: str
    warning_threshold_readable: str


class CommitStatusMessageStrategy(MessageStrategyInterface):
    def build_message(self, context: CommitStatusNotificationContext) -> str | bytes:
        if context.should_use_upgrade_comment:
            return self.build_upgrade_message(context)
        else:
            return self.build_default_message(context)

    @sentry_sdk.trace
    def build_default_message(
        self, context: CommitStatusNotificationContext
    ) -> str | bytes:
        template = loader.get_template(
            "bundle_analysis_notify/commit_status_summary.md"
        )
        # Prefix message is based on the commit status level
        prefix_message = {
            CommitStatusLevel.INFO: "",
            CommitStatusLevel.WARNING: "Passed with Warnings - ",
            CommitStatusLevel.ERROR: "Failed - ",
        }.get(context.commit_status_level)

        warning_threshold = context.user_config.warning_threshold
        if warning_threshold.type == "absolute":
            warning_threshold_readable = bytes_readable(warning_threshold.threshold)
            absolute_change = context.bundle_analysis_comparison.total_size_delta
            change_readable = bytes_readable(absolute_change)
        else:
            warning_threshold_readable = str(warning_threshold.threshold) + "%"
            change_readable = (
                str(context.bundle_analysis_comparison.percentage_delta) + "%"
            )

        context = BundleCommentTemplateContext(
            prefix_message=prefix_message,
            change_readable=change_readable,
            warning_threshold_readable=warning_threshold_readable,
        )
        return template.render(context)

    @sentry_sdk.trace
    def build_upgrade_message(self, context: CommitStatusNotificationContext) -> str:
        author_username = context.pull.provider_pull["author"].get("username")
        return (
            f"Please activate user {author_username} to display a detailed status check"
        )

    def _cache_key(self, context: CommitStatusNotificationContext) -> str:
        return "cache:" + make_hash_sha256(
            dict(
                type="status_check_notification",
                repoid=context.repository.repoid,
                base_commitid=context.base_commit.commitid,
                head_commitid=context.commit.commitid,
                notifier_name="bundle_analysis_commit_status",
                notifier_title="codecov/bundles",
            )
        )

    @sentry_sdk.trace
    def send_message(
        self, context: CommitStatusNotificationContext, message: str | bytes
    ) -> NotificationResult:
        repository_service = context.repository_service
        cache_key = self._cache_key(context)
        last_payload = cache.get_backend().get(cache_key)
        if message == last_payload:
            return NotificationResult(
                notification_attempted=False,
                notification_successful=False,
                explanation="payload_unchanged",
            )
        try:
            async_to_sync(repository_service.set_commit_status)(
                context.commit.commitid,
                context.commit_status_level.to_str(),
                "codecov/bundles",
                message,
                context.commit_status_url,
            )
            # Update the recently-sent messages cache
            cache.get_backend().set(
                cache_key,
                context.cache_ttl,
                message,
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                github_app_used=get_github_app_used(repository_service),
            )
        except TorngitClientError:
            log.error(
                "Failed to set commit status",
                extra=dict(
                    commit=context.commit.commitid,
                    report_key=context.commit_report.external_id,
                ),
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="TorngitClientError",
            )
