import logging
from typing import Literal, TypedDict

import sentry_sdk
from django.template import loader
from shared.bundle_analysis import (
    BundleAnalysisComparison,
    BundleChange,
)
from shared.torngit.exceptions import TorngitClientError

from services.bundle_analysis.notify.contexts.comment import (
    BundleAnalysisPRCommentNotificationContext,
)
from services.bundle_analysis.notify.helpers import (
    bytes_readable,
    get_github_app_used,
)
from services.bundle_analysis.notify.messages import MessageStrategyInterface
from services.license import requires_license
from services.notification.notifiers.base import NotificationResult
from services.urls import get_bundle_analysis_pull_url, get_members_url

log = logging.getLogger(__name__)


class BundleRow(TypedDict):
    bundle_name: str
    bundle_size: str
    change_size_readable: str
    change_icon: str
    has_cached: bool


class BundleCommentTemplateContext(TypedDict):
    pull_url: str
    total_size_delta: int
    total_size_readable: str
    total_percentage: str
    status_level: Literal["INFO"] | Literal["WARNING"] | Literal["ERROR"]
    warning_threshold_readable: str
    bundle_rows: list[BundleRow]
    has_cached_bundles: bool


class UpgradeCommentTemplateContext(TypedDict):
    author_username: str
    is_saas: bool
    activation_link: str


class BundleAnalysisCommentMarkdownStrategy(MessageStrategyInterface):
    def build_message(
        self, context: BundleAnalysisPRCommentNotificationContext
    ) -> str | bytes:
        if context.should_use_upgrade_comment:
            return self.build_upgrade_message(context)
        else:
            return self.build_default_message(context)

    @sentry_sdk.trace
    def build_default_message(
        self, context: BundleAnalysisPRCommentNotificationContext
    ) -> str:
        template = loader.get_template("bundle_analysis_notify/bundle_comment.md")
        total_size_delta = context.bundle_analysis_comparison.total_size_delta
        bundle_rows = self._create_bundle_rows(context.bundle_analysis_comparison)
        warning_threshold = context.user_config.warning_threshold
        if warning_threshold.type == "absolute":
            warning_threshold_readable = bytes_readable(warning_threshold.threshold)
        else:
            warning_threshold_readable = str(round(warning_threshold.threshold)) + "%"
        context = BundleCommentTemplateContext(
            has_cached=any(row["is_cached"] for row in bundle_rows),
            bundle_rows=bundle_rows,
            pull_url=get_bundle_analysis_pull_url(pull=context.pull.database_pull),
            total_size_delta=total_size_delta,
            status_level=context.commit_status_level.name,
            total_percentage=str(
                round(context.bundle_analysis_comparison.percentage_delta, 2)
            )
            + "%",
            total_size_readable=bytes_readable(total_size_delta),
            warning_threshold_readable=warning_threshold_readable,
        )
        return template.render(context)

    @sentry_sdk.trace
    def build_upgrade_message(
        self, context: BundleAnalysisPRCommentNotificationContext
    ) -> str:
        template = loader.get_template("bundle_analysis_notify/upgrade_comment.md")
        context = UpgradeCommentTemplateContext(
            activation_link=get_members_url(context.pull.database_pull),
            is_saas=not requires_license(),
            author_username=context.pull.provider_pull["author"].get("username"),
        )
        return template.render(context)

    @sentry_sdk.trace
    async def send_message(
        self, context: BundleAnalysisPRCommentNotificationContext, message: str
    ) -> NotificationResult:
        pull = context.pull.database_pull
        repository_service = context.repository_service
        try:
            comment_id = pull.bundle_analysis_commentid
            if comment_id:
                await repository_service.edit_comment(pull.pullid, comment_id, message)
            else:
                res = await repository_service.post_comment(pull.pullid, message)
                pull.bundle_analysis_commentid = res["id"]
            return NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                github_app_used=get_github_app_used(repository_service),
            )
        except TorngitClientError:
            log.error(
                "Error creating/updating PR comment",
                extra=dict(
                    commit=context.commit.commitid,
                    report_key=context.commit_report.external_id,
                    pullid=pull.pullid,
                ),
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="TorngitClientError",
            )

    def _create_bundle_rows(
        self,
        comparison: BundleAnalysisComparison,
    ) -> list[BundleRow]:
        bundle_rows = []
        bundle_changes = comparison.bundle_changes()
        # Calculate bundle change data in one loop since bundle_changes is a generator
        for bundle_change in bundle_changes:
            # Define row table data
            bundle_name = bundle_change.bundle_name
            if bundle_change.change_type == BundleChange.ChangeType.REMOVED:
                size = "(removed)"
                is_cached = False
            else:
                head_bundle_report = comparison.head_report.bundle_report(bundle_name)
                size = bytes_readable(head_bundle_report.total_size())
                is_cached = head_bundle_report.is_cached()

            change_size = bundle_change.size_delta
            if change_size == 0:
                # Don't include bundles that were not changes in the table
                continue
            icon = ""
            if change_size > 0:
                icon = ":arrow_up:"
            elif change_size < 0:
                icon = ":arrow_down:"

            bundle_rows.append(
                BundleRow(
                    bundle_name=bundle_name,
                    bundle_size=size,
                    change_size_readable=bytes_readable(change_size),
                    change_icon=icon,
                    is_cached=is_cached,
                )
            )

        return bundle_rows
