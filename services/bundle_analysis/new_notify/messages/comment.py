import logging
from typing import TypedDict

import sentry_sdk
from django.template import loader
from shared.bundle_analysis import (
    BundleAnalysisComparison,
    BundleChange,
)
from shared.torngit.exceptions import TorngitClientError

from services.bundle_analysis.new_notify.contexts.comment import (
    BundleAnalysisPRCommentNotificationContext,
)
from services.bundle_analysis.new_notify.helpers import (
    bytes_readable,
    get_github_app_used,
)
from services.bundle_analysis.new_notify.messages import MessageStrategyInterface
from services.notification.notifiers.base import NotificationResult
from services.urls import get_bundle_analysis_pull_url

log = logging.getLogger(__name__)


class BundleRow(TypedDict):
    bundle_name: str
    bundle_size: str
    change_size_readable: str
    change_icon: str


class BundleCommentTemplateContext(TypedDict):
    pull_url: str
    total_size_delta: int
    total_size_readable: str
    bundle_rows: list[BundleRow]


class BundleAnalysisCommentMarkdownStrategy(MessageStrategyInterface):
    @sentry_sdk.trace
    def build_message(self, context: BundleAnalysisPRCommentNotificationContext) -> str:
        template = loader.get_template("bundle_analysis_notify/bundle_comment.md")
        total_size_delta = context.bundle_analysis_comparison.total_size_delta
        context = BundleCommentTemplateContext(
            bundle_rows=self._create_bundle_rows(context.bundle_analysis_comparison),
            pull_url=get_bundle_analysis_pull_url(pull=context.pull.database_pull),
            total_size_delta=total_size_delta,
            total_size_readable=bytes_readable(total_size_delta),
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
    ) -> tuple[BundleRow]:
        bundle_rows = []
        bundle_changes = comparison.bundle_changes()
        # Calculate bundle change data in one loop since bundle_changes is a generator
        for bundle_change in bundle_changes:
            # Define row table data
            bundle_name = bundle_change.bundle_name
            if bundle_change.change_type == BundleChange.ChangeType.REMOVED:
                size = "(removed)"
            else:
                head_bundle_report = comparison.head_report.bundle_report(bundle_name)
                size = bytes_readable(head_bundle_report.total_size())

            change_size = bundle_change.size_delta
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
                )
            )

        return bundle_rows
