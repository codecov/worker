from functools import cached_property

from shared.bundle_analysis import (
    BundleAnalysisReport,
    BundleAnalysisReportLoader,
)
from shared.torngit.base import TorngitBaseAdapter
from shared.yaml import UserYaml

from database.enums import ReportType
from database.models.core import Commit, Repository
from database.models.reports import CommitReport
from services.archive import ArchiveService
from services.bundle_analysis.new_notify.types import NotificationType
from services.repository import (
    get_repo_provider_service,
)
from services.storage import get_storage_client


class BaseBundleAnalysisNotificationContext:
    notification_type: NotificationType

    def __init__(
        self, commit: Commit, current_yaml: UserYaml, gh_app_installation_name: str
    ) -> None:
        self.commit = commit
        self.current_yaml = current_yaml
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

    @property
    def commit_report(self) -> CommitReport:
        return self._commit_report

    @commit_report.setter
    def commit_report(self, report: CommitReport) -> None:
        self._commit_report = report

    @property
    def bundle_analysis_report(self) -> BundleAnalysisReport:
        return self._bundle_analysis_report

    @bundle_analysis_report.setter
    def bundle_analysis_report(self, report: BundleAnalysisReport) -> None:
        self._bundle_analysis_report = report


class NotificationContextBuildError(Exception):
    def __init__(self, failed_step: str, detail: str | None = None) -> None:
        super()
        self.failed_step = failed_step
        self.detail = detail


class WrongContextBuilderError(Exception):
    pass


class NotificationContextBuilder:
    # TODO: Find a way to re-use the base-context (by cloning it instead of recreating it for every notification)
    # The annoying bit is creating a specialized class from the base one without having to nitpick the details
    # @classmethod
    # def clone_builder(
    #     cls, builder: "NotificationContextBuilder"
    # ) -> "NotificationContextBuilder":
    #     context_copy = deepcopy(builder._notification_context)
    #     new_builder = cls()
    #     new_builder._notification_context = context_copy
    #     new_builder.commit_report_loaded = builder.commit_report_loaded
    #     new_builder.bundle_analysis_report_loaded = (
    #         builder.bundle_analysis_report_loaded
    #     )
    #     return new_builder

    def initialize(
        self, commit: Commit, current_yaml: UserYaml, gh_app_installation_name: str
    ) -> "NotificationContextBuilder":
        self._notification_context = BaseBundleAnalysisNotificationContext(
            commit=commit,
            current_yaml=current_yaml,
            gh_app_installation_name=gh_app_installation_name,
        )
        return self

    def load_commit_report(self) -> "NotificationContextBuilder":
        """Loads the CommitReport into the NotificationContext
        Raises: Fail if no CommitReport
        """
        commit_report = self._notification_context.commit.commit_report(
            report_type=ReportType.BUNDLE_ANALYSIS
        )
        if commit_report is None:
            raise NotificationContextBuildError("load_commit_report")
        self._notification_context.commit_report = commit_report
        return self

    def load_bundle_analysis_report(self) -> "NotificationContextBuilder":
        """Loads the BundleAnalysisReport into the NotificationContext
        Raises: Fail if no BundleAnalysisReport
        """
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

    def build_context(self) -> "NotificationContextBuilder":
        """Raises: Fail if any of the build steps fail"""
        self.load_commit_report()
        self.load_bundle_analysis_report()
        return self

    def get_result(self) -> BaseBundleAnalysisNotificationContext:
        return self._notification_context
