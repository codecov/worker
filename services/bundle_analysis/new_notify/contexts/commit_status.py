from enum import Enum, auto
from typing import Literal

from asgiref.sync import async_to_sync
from shared.bundle_analysis import (
    BundleAnalysisComparison,
)
from shared.config import get_config
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
from services.bundle_analysis.new_notify.helpers import (
    is_bundle_change_within_bundle_threshold,
)
from services.bundle_analysis.new_notify.types import NotificationType
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
)
from services.urls import get_bundle_analysis_pull_url, get_commit_url


class CommitStatusLevel(Enum):
    INFO = auto()
    WARNING = auto()
    ERROR = auto()

    def to_str(self) -> Literal["success"] | Literal["failure"]:
        if self.value == "ERROR":
            return "failure"
        return "success"


class CommitStatusNotificationContext(BaseBundleAnalysisNotificationContext):
    notification_type = NotificationType.COMMIT_STATUS

    pull: EnrichedPull | None = NotificationContextField[EnrichedPull | None]()
    bundle_analysis_comparison: BundleAnalysisComparison = NotificationContextField[
        BundleAnalysisComparison
    ]()
    commit_status_level: CommitStatusLevel = NotificationContextField[
        CommitStatusLevel
    ]()
    commit_status_url: str = NotificationContextField[str]()
    cache_ttl: int = NotificationContextField[int]()

    @property
    def base_commit(self) -> Commit:
        if self.pull:
            return self.pull.database_pull.get_comparedto_commit()
        return self.commit.get_parent_commit()


class CommitStatusNotificationContextBuilder(NotificationContextBuilder):
    fields_of_interest: tuple[str] = (
        "commit_report",
        "bundle_analysis_report",
        "user_config",
        "pull",
        "bundle_analysis_comparison",
    )

    def initialize(
        self, commit: Commit, current_yaml: UserYaml, gh_app_installation_name: str
    ) -> "CommitStatusNotificationContextBuilder":
        self.current_yaml = current_yaml
        self._notification_context = CommitStatusNotificationContext(
            commit=commit,
            gh_app_installation_name=gh_app_installation_name,
        )
        return self

    async def load_optional_enriched_pull(
        self,
    ) -> "CommitStatusNotificationContextBuilder":
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

    def load_bundle_comparison(
        self,
    ) -> "CommitStatusNotificationContextBuilder":
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

    def load_commit_status_level(self) -> "CommitStatusNotificationContextBuilder":
        bundle_analysis_comparison = (
            self._notification_context.bundle_analysis_comparison
        )
        user_config = self._notification_context.user_config

        if is_bundle_change_within_bundle_threshold(
            bundle_analysis_comparison, user_config.warning_threshold
        ):
            self._notification_context.commit_status_level = CommitStatusLevel.INFO
        elif user_config.status_level == "informational":
            self._notification_context.commit_status_level = CommitStatusLevel.WARNING
        else:
            self._notification_context.commit_status_level = CommitStatusLevel.ERROR
        return self

    def load_commit_status_url(self) -> "CommitStatusNotificationContextBuilder":
        if self._notification_context.pull:
            self._notification_context.commit_status_url = get_bundle_analysis_pull_url(
                self._notification_context.pull.database_pull
            )
        else:
            self._notification_context.commit_status_url = get_commit_url(
                self._notification_context.commit
            )
        return self

    def load_cache_ttl(self) -> "CommitStatusNotificationContextBuilder":
        self._notification_context.cache_ttl = int(
            # using `get_config` instead of `current_yaml` because
            # `current_yaml` does not include the install configuration
            get_config("setup", "cache", "send_status_notification", default=600)
        )  # 10 min default
        return self

    def build_context(self) -> "CommitStatusNotificationContextBuilder":
        super().build_context()
        async_to_sync(self.load_optional_enriched_pull)()
        self.load_bundle_comparison()
        self.load_commit_status_level()
        self.load_commit_status_url()
        self.load_cache_ttl()
        return self

    def get_result(self) -> CommitStatusNotificationContext:
        return self._notification_context
