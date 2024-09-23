import logging
from typing import Self

import sentry_sdk
from asgiref.sync import async_to_sync
from shared.bundle_analysis import (
    BundleAnalysisComparison,
)
from shared.yaml import UserYaml

from database.models.core import Commit
from services.activation import activate_user, schedule_new_user_activated_task
from services.bundle_analysis.comparison import ComparisonLoader
from services.bundle_analysis.exceptions import (
    MissingBaseCommit,
    MissingBaseReport,
    MissingHeadCommit,
    MissingHeadReport,
)
from services.bundle_analysis.notify.contexts import (
    BaseBundleAnalysisNotificationContext,
    CommitStatusLevel,
    NotificationContextBuilder,
    NotificationContextBuildError,
    NotificationContextField,
)
from services.bundle_analysis.notify.helpers import (
    is_bundle_comparison_change_within_configured_threshold,
)
from services.bundle_analysis.notify.types import NotificationType
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
)
from services.seats import ShouldActivateSeat, determine_seat_activation

log = logging.getLogger(__name__)


class BundleAnalysisPRCommentNotificationContext(BaseBundleAnalysisNotificationContext):
    """Context for the Bundle Analysis PR Comment. Extends BaseBundleAnalysisNotificationContext."""

    notification_type = NotificationType.PR_COMMENT

    pull: EnrichedPull = NotificationContextField[EnrichedPull]()
    bundle_analysis_comparison: BundleAnalysisComparison = NotificationContextField[
        BundleAnalysisComparison
    ]()
    commit_status_level: CommitStatusLevel = NotificationContextField[
        CommitStatusLevel
    ]()
    should_use_upgrade_comment: bool = NotificationContextField[bool]()


class BundleAnalysisPRCommentContextBuilder(NotificationContextBuilder):
    fields_of_interest: tuple[str] = (
        "commit_report",
        "bundle_analysis_report",
        "user_config",
        "pull",
        "bundle_analysis_comparison",
        "should_use_upgrade_comment",
    )

    def initialize(
        self, commit: Commit, current_yaml: UserYaml, gh_app_installation_name: str
    ) -> "BundleAnalysisPRCommentContextBuilder":
        self.current_yaml = current_yaml
        self._notification_context = BundleAnalysisPRCommentNotificationContext(
            commit=commit,
            gh_app_installation_name=gh_app_installation_name,
        )
        return self

    @sentry_sdk.trace
    async def load_enriched_pull(self) -> Self:
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
            self.current_yaml,
        )
        if pull is None:
            raise NotificationContextBuildError("load_enriched_pull")
        self._notification_context.pull = pull
        return self

    @sentry_sdk.trace
    def load_bundle_comparison(self) -> Self:
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
            comparison = ComparisonLoader.from_EnrichedPull(pull).get_comparison()
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

    def evaluate_has_enough_changes(self) -> Self:
        """Evaluates if the NotificationContext includes enough changes to send the notification.
        Configuration is done via UserYaml.
        If a comment was previously made for this PR the required changes are bypassed so that we
        update the existing comment with the latest information.
        Raises:
            NotificationContextBuildError: required changes are not met.
        """
        pull = self._notification_context.pull
        required_changes_threshold = (
            self._notification_context.user_config.required_changes_threshold
        )
        required_changes = self._notification_context.user_config.required_changes
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
            True: not is_bundle_comparison_change_within_configured_threshold(
                comparison,
                required_changes_threshold,
                compare_non_negative_numbers=True,
            ),
            "bundle_increase": (
                comparison.total_size_delta > 0
                and not is_bundle_comparison_change_within_configured_threshold(
                    comparison,
                    required_changes_threshold,
                    compare_non_negative_numbers=True,
                )
            ),
        }.get(required_changes, True)
        if not should_continue:
            raise NotificationContextBuildError("evaluate_has_enough_changes")
        return self

    @sentry_sdk.trace
    def evaluate_should_use_upgrade_message(self) -> Self:
        activate_seat_info = determine_seat_activation(self._notification_context.pull)
        match activate_seat_info.should_activate_seat:
            case ShouldActivateSeat.AUTO_ACTIVATE:
                successful_activation = activate_user(
                    db_session=self._notification_context.commit.get_db_session(),
                    org_ownerid=activate_seat_info.owner_id,
                    user_ownerid=activate_seat_info.author_id,
                )
                if successful_activation:
                    schedule_new_user_activated_task(
                        activate_seat_info.owner_id,
                        activate_seat_info.author_id,
                    )
                    self._notification_context.should_use_upgrade_comment = False
                else:
                    self._notification_context.should_use_upgrade_comment = True
            case ShouldActivateSeat.MANUAL_ACTIVATE:
                self._notification_context.should_use_upgrade_comment = True
            case ShouldActivateSeat.NO_ACTIVATE:
                self._notification_context.should_use_upgrade_comment = False
        return self

    def load_commit_status_level(self) -> Self:
        bundle_analysis_comparison = (
            self._notification_context.bundle_analysis_comparison
        )
        user_config = self._notification_context.user_config

        if is_bundle_comparison_change_within_configured_threshold(
            bundle_analysis_comparison, user_config.warning_threshold
        ):
            self._notification_context.commit_status_level = CommitStatusLevel.INFO
        elif user_config.status_level == "informational":
            self._notification_context.commit_status_level = CommitStatusLevel.WARNING
        else:
            self._notification_context.commit_status_level = CommitStatusLevel.ERROR
        return self

    def build_context(self) -> Self:
        super().build_context()
        async_to_sync(self.load_enriched_pull)()
        return (
            self.load_bundle_comparison()
            .evaluate_has_enough_changes()
            .evaluate_should_use_upgrade_message()
            .load_commit_status_level()
        )

    def get_result(self) -> BundleAnalysisPRCommentNotificationContext:
        return self._notification_context
