import logging
from typing import Literal

from asgiref.sync import async_to_sync
from shared.bundle_analysis import (
    BundleAnalysisComparison,
)

from services.bundle_analysis.comparison import ComparisonLoader
from services.bundle_analysis.notify.contexts import (
    BaseBundleAnalysisNotificationContext,
    NotificationContextBuilder,
    NotificationContextBuildError,
    WrongContextBuilderError,
)
from services.bundle_analysis.notify.types import NotificationType
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
)

log = logging.getLogger(__name__)


class BundleAnalysisCommentNotificationContext(BaseBundleAnalysisNotificationContext):
    notification_type = NotificationType.PR_COMMENT

    @property
    def pull(self) -> EnrichedPull:
        return self._pull

    @pull.setter
    def pull(self, pull: EnrichedPull):
        self._pull = pull

    @property
    def bundle_analysis_comparison(self) -> BundleAnalysisComparison:
        return self._bundle_analysis_comparison

    @bundle_analysis_comparison.setter
    def bundle_analysis_comparison(self, comparison: BundleAnalysisComparison):
        self._bundle_analysis_comparison = comparison


class BundleAnalysisCommentContextBuilder(NotificationContextBuilder):
    async def load_enriched_pull(self) -> None:
        """Loads the EnrichedPull into the NotificationContext
        Raises: Fail if no EnrichedPull
        """
        pull: (
            EnrichedPull | None
        ) = await fetch_and_update_pull_request_information_from_commit(
            self._notification_context.repository_service,
            self._notification_context.commit,
            self._notification_context.current_yaml,
        )
        if pull is None:
            raise NotificationContextBuildError("load_enriched_pull")
        self._notification_context.pull = pull

    def load_bundle_comparison(self) -> None:
        pull = self._notification_context.pull
        comparison = ComparisonLoader(pull).get_comparison()
        self._notification_context.bundle_analysis_comparison = comparison

    def evaluate_has_enough_changes(self) -> None:
        """Evaluates if the NotificationContext includes enough changes to send the notification
        Aborts notification if there are not enough changes
        """
        current_yaml = self._notification_context.current_yaml
        required_changes: bool | Literal["bundle_increase"] = (
            current_yaml.read_yaml_field(
                "comment", "require_bundle_changes", _else=False
            )
        )
        changes_threshold: int = current_yaml.read_yaml_field(
            "comment", "bundle_change_threshold", _else=0
        )
        pull = self._notify_context.pull
        if pull.database_pull.bundle_analysis_commentid:
            log.info(
                "Skipping required_changes verification because comment already exists",
                extra=dict(pullid=pull.database_pull.id, commitid=self.commit.commitid),
            )
            return True

        comparison = self._notify_context.bundle_analysis_comparison
        should_continue = {
            False: True,
            True: abs(comparison.total_size_delta) > changes_threshold,
            "bundle_increase": (
                comparison.total_size_delta > 0
                and comparison.total_size_delta > changes_threshold
            ),
        }.get(required_changes, default=True)
        if not should_continue:
            raise NotificationContextBuildError("evaluate_has_enough_changes")

    def build_specialized_context(
        self, notification_type: NotificationType
    ) -> BundleAnalysisCommentNotificationContext:
        if notification_type != NotificationType.PR_COMMENT:
            msg = f"Wrong notification type for BundleAnalysisCommentContextBuilder. Expected PR_COMMENT, received {notification_type.name}"
            raise WrongContextBuilderError(msg)
        self.build_base_context()
        async_to_sync(self.load_enriched_pull())
        self.load_bundle_comparison()
        self.evaluate_has_enough_changes()
        return self._notification_context
