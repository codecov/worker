from functools import cached_property

from shared.bundle_analysis import (
    BundleAnalysisComparison,
    BundleAnalysisReportLoader,
)
from shared.storage import get_appropriate_storage_service

from database.enums import ReportType
from database.models.core import Commit, Repository
from database.models.reports import CommitReport
from services.archive import ArchiveService
from services.bundle_analysis.exceptions import (
    MissingBaseCommit,
    MissingBaseReport,
    MissingHeadCommit,
    MissingHeadReport,
)
from services.repository import EnrichedPull


class ComparisonLoader:
    def __init__(self, base_commit: Commit | None, head_commit: Commit | None):
        self._base_commit: Commit | None = base_commit
        self._head_commit: Commit | None = head_commit

    @classmethod
    def from_EnrichedPull(cls, pull: EnrichedPull) -> "ComparisonLoader":
        return cls(
            base_commit=pull.database_pull.get_comparedto_commit(),
            head_commit=pull.database_pull.get_head_commit(),
        )

    @cached_property
    def repository(self) -> Repository:
        return self.head_commit.repository

    @cached_property
    def base_commit(self) -> Commit:
        commit = self._base_commit
        if commit is None:
            raise MissingBaseCommit()
        return commit

    @cached_property
    def head_commit(self) -> Commit:
        commit = self._head_commit
        if commit is None:
            raise MissingHeadCommit()
        return commit

    @cached_property
    def base_commit_report(self) -> CommitReport:
        commit_report = self.base_commit.commit_report(
            report_type=ReportType.BUNDLE_ANALYSIS
        )
        if commit_report is None:
            raise MissingBaseReport()
        return commit_report

    @cached_property
    def head_commit_report(self) -> CommitReport:
        commit_report = self.head_commit.commit_report(
            report_type=ReportType.BUNDLE_ANALYSIS
        )
        if commit_report is None:
            raise MissingHeadReport()
        return commit_report

    def get_comparison(self) -> BundleAnalysisComparison:
        loader = BundleAnalysisReportLoader(
            storage_service=get_appropriate_storage_service(),
            repo_key=ArchiveService.get_archive_hash(self.repository),
        )

        return BundleAnalysisComparison(
            loader=loader,
            base_report_key=self.base_commit_report.external_id,
            head_report_key=self.head_commit_report.external_id,
            repository=self.repository.repoid,
        )
