import logging
from typing import TypedDict

import sentry_sdk
from django.template import loader
from shared.helpers.cache import make_hash_sha256
from shared.torngit.exceptions import TorngitClientError

from helpers.cache import cache
from services.bundle_analysis.notify.contexts.commit_status import (
    CommitStatusLevel,
    CommitStatusNotificationContext,
)
from services.bundle_analysis.notify.helpers import (
    bytes_readable,
    get_github_app_used,
)
from services.bundle_analysis.notify.messages import MessageStrategyInterface
from services.notification.notifiers.base import NotificationResult

log = logging.getLogger(__name__)


class BundleCommentTemplateContext(TypedDict):
    prefix_message: str
    change_readable: str
    warning_threshold_readable: str


class CommitStatusMessageStrategy(MessageStrategyInterface):
    @sentry_sdk.trace
    def build_message(self, context: CommitStatusNotificationContext) -> str | bytes:
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
            is_negative = absolute_change < 0
            change_readable = ("-" if is_negative else "") + bytes_readable(
                absolute_change
            )
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

    def _cache_key(self, context: CommitStatusNotificationContext) -> str:
        return make_hash_sha256(
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
    async def send_message(
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
            await repository_service.set_commit_status(
                commit=context.commit.commitid,
                status=context.commit_status_level.to_str(),
                context="codecov/bundles",
                description=message,
                url=context.commit_status_url,
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
