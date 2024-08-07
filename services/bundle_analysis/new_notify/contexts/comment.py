import logging
from typing import Literal

from asgiref.sync import async_to_sync
from shared.bundle_analysis import (
    BundleAnalysisComparison,
)
from shared.yaml import UserYaml

from database.models.core import Commit
from services.bundle_analysis.comparison import ComparisonLoader
from services.bundle_analysis.exceptions import (
    MissingBaseCommit,
    MissingBaseReport,
    MissingHeadCommit,
    MissingHeadReport,
)
from services.bundle_analysis.new_notify.contexts import (
    BaseBundleAnalysisNotificationContext,
    NotificationContextBuilder,
    NotificationContextBuildError,
    NotificationContextField,
)
from services.bundle_analysis.new_notify.types import NotificationType
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
)

log = logging.getLogger(__name__)


class BundleAnalysisPRCommentNotificationContext(BaseBundleAnalysisNotificationContext):
    """Context for the Bundle Analysis PR Comment. Extends BaseBundleAnalysisNotificationContext."""

    notification_type = NotificationType.PR_COMMENT

    pull: EnrichedPull = NotificationContextField[EnrichedPull]()
    bundle_analysis_comparison: BundleAnalysisComparison = NotificationContextField[
        BundleAnalysisComparison
    ]()


class BundleAnalysisPRCommentContextBuilder(NotificationContextBuilder):
    def initialize(
        self, commit: Commit, current_yaml: UserYaml, gh_app_installation_name: str
    ) -> "BundleAnalysisPRCommentContextBuilder":
        self._notification_context = BundleAnalysisPRCommentNotificationContext(
            commit=commit,
            current_yaml=current_yaml,
            gh_app_installation_name=gh_app_installation_name,
        )
        return self

    def initialize_from_context(
        self, context: BundleAnalysisPRCommentNotificationContext
    ) -> "BundleAnalysisPRCommentContextBuilder":
        self.initialize(
            commit=context.commit,
            current_yaml=context.current_yaml,
            gh_app_installation_name=context.gh_app_installation_name,
        )
        fields_of_interest = [
            "commit_report",
            "bundle_analysis_report",
            "pull",
            "bundle_analysis_comparison",
        ]
        for field_name in fields_of_interest:
            if field_name in context.__dict__:
                self._notification_context.__dict__[field_name] = context.__dict__[
                    field_name
                ]
        return self

    async def load_enriched_pull(self) -> "BundleAnalysisPRCommentContextBuilder":
        """Loads the EnrichedPull into the NotificationContext.
        EnrichedPull includes updated info from the git provider and info saved in the database.
        Raises:
            NotificationContextBuildError: failed to get EnrichedPull.
                This can be because there's no Pull saved in the database,
                or because we couldn't update the pull's info from the git provider.
        """
        if self.is_field_loaded("pull"):
            return self
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
        return self

    def load_bundle_comparison(self) -> "BundleAnalysisPRCommentContextBuilder":
        """Loads the BundleAnalysisComparison into the NotificationContext.
        BundleAnalysisComparison is the diff between 2 BundleAnalysisReports,
        respectively the one for the pull's base and one for the pull's head.
        Raises:
            NotificationContextBuildError: missing some information necessary to create
                the BundleAnalysisComparison.
        """
        if self.is_field_loaded("bundle_analysis_comparison"):
            return self
        pull = self._notification_context.pull
        try:
            comparison = ComparisonLoader(pull).get_comparison()
            self._notification_context.bundle_analysis_comparison = comparison
            return self
        except (
            MissingBaseCommit,
            MissingHeadCommit,
            MissingBaseReport,
            MissingHeadReport,
        ) as exp:
            raise NotificationContextBuildError(
                "load_bundle_comparison", detail=exp.__class__.__name__
            )

    def evaluate_has_enough_changes(self) -> "BundleAnalysisPRCommentContextBuilder":
        """Evaluates if the NotificationContext includes enough changes to send the notification.
        Configuration is done via UserYaml.
        If a comment was previously made for this PR the required changes are bypassed so that we
        update the existing comment with the latest information.
        Raises:
            NotificationContextBuildError: required changes are not met.
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
        pull = self._notification_context.pull
        if pull.database_pull.bundle_analysis_commentid:
            log.info(
                "Skipping required_changes verification because comment already exists",
                extra=dict(
                    pullid=pull.database_pull.id,
                    commitid=self._notification_context.commit.commitid,
                ),
            )
            return self
        comparison = self._notification_context.bundle_analysis_comparison
        should_continue = {
            False: True,
            True: abs(comparison.total_size_delta) > changes_threshold,
            "bundle_increase": (
                comparison.total_size_delta > 0
                and comparison.total_size_delta > changes_threshold
            ),
        }.get(required_changes, True)
        if not should_continue:
            raise NotificationContextBuildError("evaluate_has_enough_changes")
        return self

    def build_context(self) -> "BundleAnalysisPRCommentContextBuilder":
        super().build_context()
        async_to_sync(self.load_enriched_pull)()
        self.load_bundle_comparison()
        self.evaluate_has_enough_changes()
        return self

    def get_result(self) -> BundleAnalysisPRCommentNotificationContext:
        return self._notification_context
