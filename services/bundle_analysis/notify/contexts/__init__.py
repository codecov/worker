from enum import Enum, auto
from functools import cached_property
from typing import Generic, Literal, Self, TypeVar

import sentry_sdk
from shared.bundle_analysis import (
    BundleAnalysisReport,
    BundleAnalysisReportLoader,
)
from shared.torngit.base import TorngitBaseAdapter
from shared.validation.types import BundleThreshold
from shared.yaml import UserYaml

from database.enums import ReportType
from database.models.core import Commit, Repository
from database.models.reports import CommitReport
from services.archive import ArchiveService
from services.bundle_analysis.notify.helpers import to_BundleThreshold
from services.bundle_analysis.notify.types import (
    NotificationType,
    NotificationUserConfig,
)
from services.repository import (
    get_repo_provider_service,
)
from services.storage import get_storage_client

T = TypeVar("T")


class ContextNotLoadedError(Exception):
    pass


class CommitStatusLevel(Enum):
    INFO = auto()
    WARNING = auto()
    ERROR = auto()

    def to_str(self) -> Literal["success"] | Literal["failure"]:
        if self.value == "ERROR":
            return "failure"
        return "success"


class NotificationContextField(Generic[T]):
    """NotificationContextField is a descriptor akin to a Django model field.
    If you create one as a class member named `foo`, it will define the behavior to get and set an instance member named `foo`.
    It is also similar to @property
    """

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __get__(self, instance: "NotificationContextField", owner) -> T:
        if self._name not in instance.__dict__:
            msg = f"Property {self._name} is not loaded. Make sure to build the context before using it."
            raise ContextNotLoadedError(msg)
        return instance.__dict__[self._name]

    def __set__(self, instance: "NotificationContextField", value: T) -> None:
        instance.__dict__[self._name] = value


class BaseBundleAnalysisNotificationContext:
    """Base NotificationContext for bundle analysis notifications.
    It includes basic information that all bundle analysis notifications need.
    Use NotificationContextBuilder to populate the context.

    Example:
      builder = NotificationContextBuilder(commit, current_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME)
      notification_context = builder.build_context().get_result()
    """

    notification_type: NotificationType

    def __init__(self, commit: Commit, gh_app_installation_name: str) -> None:
        self.commit = commit
        self.gh_app_installation_name = gh_app_installation_name

    @cached_property
    def repository(self) -> Repository:
        return self.commit.repository

    @cached_property
    def repository_service(self) -> TorngitBaseAdapter:
        return get_repo_provider_service(
            self.repository,
            installation_name_to_use=self.gh_app_installation_name,
        )

    commit_report: CommitReport = NotificationContextField[CommitReport]()
    bundle_analysis_report: BundleAnalysisReport = NotificationContextField[
        BundleAnalysisReport
    ]()
    user_config: NotificationUserConfig = NotificationContextField[
        NotificationUserConfig
    ]()


class NotificationContextBuildError(Exception):
    def __init__(self, failed_step: str, detail: str | None = None) -> None:
        super().__init__(failed_step, detail)
        self.failed_step = failed_step
        self.detail = detail


class WrongContextBuilderError(Exception):
    pass


class NotificationContextBuilder:
    """Creates the BaseBundleAnalysisNotificationContext one step at a time, in the correct order."""

    current_yaml: UserYaml
    """ Used with `initialize_from_context` method. Declare the fields the class wants to copy over when initializing from another context."""
    fields_of_interest: tuple[str] = (
        "commit_report",
        "bundle_analysis_report",
        "user_config",
    )

    def initialize(
        self, commit: Commit, current_yaml: UserYaml, gh_app_installation_name: str
    ) -> "NotificationContextBuilder":
        self.current_yaml = current_yaml
        self._notification_context = BaseBundleAnalysisNotificationContext(
            commit=commit,
            gh_app_installation_name=gh_app_installation_name,
        )
        return self

    def initialize_from_context(
        self, current_yaml: UserYaml, context: BaseBundleAnalysisNotificationContext
    ) -> Self:
        self.initialize(
            commit=context.commit,
            current_yaml=current_yaml,
            gh_app_installation_name=context.gh_app_installation_name,
        )

        for field_name in self.fields_of_interest:
            if field_name in context.__dict__:
                self._notification_context.__dict__[field_name] = context.__dict__[
                    field_name
                ]
        return self

    def is_field_loaded(self, field_name: str):
        return field_name in self._notification_context.__dict__

    def load_commit_report(self) -> "NotificationContextBuilder":
        """Loads the CommitReport into the NotificationContext
        Raises:
            NotificationContextBuildError: no CommitReport exist for the commit
        """
        if self.is_field_loaded("commit_report"):
            return self
        commit_report = self._notification_context.commit.commit_report(
            report_type=ReportType.BUNDLE_ANALYSIS
        )
        if commit_report is None:
            raise NotificationContextBuildError("load_commit_report")
        self._notification_context.commit_report = commit_report
        return self

    @sentry_sdk.trace
    def load_bundle_analysis_report(self) -> "NotificationContextBuilder":
        """Loads the BundleAnalysisReport into the NotificationContext
        BundleAnalysisReport is an SQLite report generated by processing uploads
        Raises:
            NotificationContextBuildError: no BundleAnalysisReport exists for the commit.
        """
        if self.is_field_loaded("bundle_analysis_report"):
            return self
        repo_hash = ArchiveService.get_archive_hash(
            self._notification_context.repository
        )
        storage_service = get_storage_client()
        analysis_report_loader = BundleAnalysisReportLoader(storage_service, repo_hash)
        bundle_analysis_report = analysis_report_loader.load(
            self._notification_context.commit_report.external_id
        )
        if bundle_analysis_report is None:
            raise NotificationContextBuildError("load_bundle_analysis_report")
        self._notification_context.bundle_analysis_report = bundle_analysis_report
        return self

    def load_user_config(self) -> "NotificationContextBuilder":
        """Parses the configuration from the `current_yaml` related to bundle analysis notification
        into a NotificationUserConfig object for the context.

        This allows all notifiers to access configuration for any notifier and already have the defaults
        """
        required_changes: bool | Literal["bundle_increase"] = (
            self.current_yaml.read_yaml_field(
                "comment", "require_bundle_changes", _else=False
            )
        )
        required_changes_threshold: int | float = self.current_yaml.read_yaml_field(
            "comment",
            "bundle_change_threshold",
            _else=BundleThreshold("absolute", 0),
        )
        warning_threshold: int | float = self.current_yaml.read_yaml_field(
            "bundle_analysis",
            "warning_threshold",
            _else=BundleThreshold("percentage", 5.0),
        )
        status_level: bool | Literal["informational"] = (
            self.current_yaml.read_yaml_field(
                "bundle_analysis", "status", _else="informational"
            )
        )
        self._notification_context.user_config = NotificationUserConfig(
            required_changes=required_changes,
            warning_threshold=to_BundleThreshold(warning_threshold),
            status_level=status_level,
            required_changes_threshold=to_BundleThreshold(required_changes_threshold),
        )
        return self

    def build_context(self) -> "NotificationContextBuilder":
        """Calls all the steps necessary to fully load the NotificationContext
        Raises:
            NotificationContextBuildError: if any of the steps fail
        """
        self.load_user_config()
        self.load_commit_report()
        self.load_bundle_analysis_report()
        return self

    def get_result(self) -> BaseBundleAnalysisNotificationContext:
        """Returns the NotificationContext.
        Should be called after `build_context`, or you get an empty context back.
        """
        return self._notification_context
