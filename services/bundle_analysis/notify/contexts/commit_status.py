from typing import Self

import sentry_sdk
from asgiref.sync import async_to_sync
from shared.bundle_analysis import (
    BundleAnalysisComparison,
)
from shared.config import get_config
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
from services.urls import get_bundle_analysis_pull_url, get_commit_url


class CommitStatusNotificationContext(BaseBundleAnalysisNotificationContext):
    notification_type = NotificationType.COMMIT_STATUS

    pull = NotificationContextField[EnrichedPull | None]()
    bundle_analysis_comparison = NotificationContextField[BundleAnalysisComparison]()
    commit_status_level = NotificationContextField[CommitStatusLevel]()
    commit_status_url = NotificationContextField[str]()
    cache_ttl = NotificationContextField[int]()
    should_use_upgrade_comment = NotificationContextField[bool]()

    @property
    def base_commit(self) -> Commit:
        if self.pull:
            return self.pull.database_pull.get_comparedto_commit()
        return self.commit.get_parent_commit()


class CommitStatusNotificationContextBuilder(NotificationContextBuilder):
    fields_of_interest: tuple[str, ...] = (
        "commit_report",
        "bundle_analysis_report",
        "user_config",
        "pull",
        "bundle_analysis_comparison",
        "should_use_upgrade_comment",
    )

    def initialize(
        self, commit: Commit, current_yaml: UserYaml, gh_app_installation_name: str
    ) -> Self:
        self.current_yaml = current_yaml
        self._notification_context = CommitStatusNotificationContext(
            commit=commit,
            gh_app_installation_name=gh_app_installation_name,
        )
        return self

    @sentry_sdk.trace
    async def load_optional_enriched_pull(
        self,
    ) -> Self:
        """Loads an optional EnrichedPull into the NotificationContext.
        EnrichedPull includes updated info from the git provider and info saved in the database.
        If the value is None it's because the commit is not in a Pull Request
        """
        if self.is_field_loaded("pull"):
            return self
        optional_pull: (
            EnrichedPull | None
        ) = await fetch_and_update_pull_request_information_from_commit(
            self._notification_context.repository_service,
            self._notification_context.commit,
            self.current_yaml,
        )
        self._notification_context.pull = optional_pull
        return self

    @sentry_sdk.trace
    def load_bundle_comparison(
        self,
    ) -> Self:
        """Loads the BundleAnalysisComparison into the NotificationContext.
        BundleAnalysisComparison is the diff between 2 BundleAnalysisReports.
        IF pull is not None, comparison is pull's BASE vs HEAD
        ELSE comparison is HEAD vs HEAD's parent

        Raises:
            NotificationContextBuildError: missing some information necessary to create
                the BundleAnalysisComparison.
        """
        if self.is_field_loaded("bundle_analysis_comparison"):
            return self
        pull = self._notification_context.pull
        try:
            if pull is None:
                comparison = ComparisonLoader(
                    base_commit=self._notification_context.commit.get_parent_commit(),
                    head_commit=self._notification_context.commit,
                ).get_comparison()
            else:
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

    def load_commit_status_url(self) -> Self:
        if self._notification_context.pull:
            self._notification_context.commit_status_url = get_bundle_analysis_pull_url(
                self._notification_context.pull.database_pull
            )
        else:
            self._notification_context.commit_status_url = get_commit_url(
                self._notification_context.commit
            )
        return self

    def load_cache_ttl(self) -> Self:
        self._notification_context.cache_ttl = int(
            # using `get_config` instead of `current_yaml` because
            # `current_yaml` does not include the install configuration
            get_config("setup", "cache", "send_status_notification", default=600)
        )  # 10 min default
        return self

    @sentry_sdk.trace
    def evaluate_should_use_upgrade_message(self) -> Self:
        if self._notification_context.pull is None:
            self._notification_context.should_use_upgrade_comment = False
            return self
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

    def build_context(self) -> Self:
        super().build_context()
        async_to_sync(self.load_optional_enriched_pull)()
        return (
            self.load_bundle_comparison()
            .load_commit_status_level()
            .evaluate_should_use_upgrade_message()
            .load_commit_status_url()
            .load_cache_ttl()
        )

    def get_result(self) -> CommitStatusNotificationContext:
        return self._notification_context
