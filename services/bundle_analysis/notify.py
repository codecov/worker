import logging
from dataclasses import dataclass
from functools import cached_property
from typing import Iterator, List, Literal, Optional, Tuple

from shared.bundle_analysis import (
    BundleAnalysisComparison,
    BundleAnalysisReport,
    BundleAnalysisReportLoader,
    BundleChange,
)
from shared.rate_limits.exceptions import EntityRateLimitedException
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import TorngitClientError
from shared.yaml import UserYaml

from database.enums import ReportType
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    Commit,
    Repository,
)
from database.models.reports import CommitReport
from services.archive import ArchiveService
from services.bundle_analysis.comparison import ComparisonLoader
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.storage import get_storage_client
from services.urls import get_bundle_analysis_pull_url
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


@dataclass
class BundleRows:
    bundle_name: str
    size: str
    change: str


class Notifier:
    def __init__(
        self,
        commit: Commit,
        current_yaml: UserYaml,
        gh_app_installation_name: str | None = None,
    ):
        self.commit = commit
        self.current_yaml = current_yaml
        self.gh_app_installation_name = (
            gh_app_installation_name or GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )

    @cached_property
    def repository(self) -> Repository:
        return self.commit.repository

    @cached_property
    def commit_report(self) -> Optional[CommitReport]:
        return self.commit.commit_report(report_type=ReportType.BUNDLE_ANALYSIS)

    @cached_property
    def repository_service(self) -> TorngitBaseAdapter:
        try:
            return get_repo_provider_service(
                self.commit.repository,
                installation_name_to_use=self.gh_app_installation_name,
            )
        except EntityRateLimitedException as e:
            log.warning(
                f"Entity {e.entity_name} rate limited trying get the repository service. Please try again later"
            )

    @cached_property
    def bundle_analysis_loader(self):
        repo_hash = ArchiveService.get_archive_hash(self.repository)
        storage_service = get_storage_client()
        return BundleAnalysisReportLoader(storage_service, repo_hash)

    @cached_property
    def bundle_report(self) -> Optional[BundleAnalysisReport]:
        return self.bundle_analysis_loader.load(self.commit_report.external_id)

    def _has_required_changes(
        self, comparison: BundleAnalysisComparison, pull: EnrichedPull
    ) -> bool:
        """Verifies if the notifier should notify according to the configured required_changes.
        Changes are defined by the user in UserYaml. Default is "always notify".
        Required changes are bypassed if a comment already exists, because we should update the comment.
        """
        if pull.database_pull.bundle_analysis_commentid:
            log.info(
                "Skipping required_changes verification because comment already exists",
                extra=dict(pullid=pull.database_pull.id, commitid=self.commit.commitid),
            )
            return True

        required_changes: bool | Literal["bundle_increase"] = read_yaml_field(
            self.current_yaml, ("comment", "require_bundle_changes"), False
        )
        changes_threshold: int = read_yaml_field(
            self.current_yaml, ("comment", "bundle_change_threshold"), 0
        )
        match required_changes:
            case False:
                return True
            case True:
                return abs(comparison.total_size_delta) > changes_threshold
            case "bundle_increase":
                return (
                    comparison.total_size_delta > 0
                    and comparison.total_size_delta > changes_threshold
                )
            case _:
                log.warning(
                    "Unknown value for required_changes",
                    extra=dict(
                        pull=pull.database_pull.id, commitid=self.commit.commitid
                    ),
                )
                return True

    async def notify(self) -> bool:
        if self.commit_report is None:
            log.warning(
                "Missing commit report", extra=dict(commitid=self.commit.commitid)
            )
            return False

        if self.bundle_report is None:
            log.warning(
                "Missing bundle report",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=self.commit_report.external_id,
                ),
            )
            return False

        pull: Optional[
            EnrichedPull
        ] = await fetch_and_update_pull_request_information_from_commit(
            self.repository_service, self.commit, self.current_yaml
        )
        if pull is None:
            log.warning(
                "No pull for commit",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=self.commit_report.external_id,
                ),
            )
            return False

        pullid = pull.database_pull.pullid
        bundle_comparison = ComparisonLoader(pull).get_comparison()

        if not self._has_required_changes(bundle_comparison, pull):
            # Skips the comment and returns successful notification
            log.info(
                "Not enough changes to notify bundle PR comment",
                extra=dict(
                    commitid=self.commit.commitid,
                    pullid=pullid,
                ),
            )
            return True

        message = self._build_message(pull=pull, comparison=bundle_comparison)
        try:
            comment_id = pull.database_pull.bundle_analysis_commentid
            if comment_id:
                await self.repository_service.edit_comment(pullid, comment_id, message)
            else:
                res = await self.repository_service.post_comment(pullid, message)
                pull.database_pull.bundle_analysis_commentid = res["id"]
            return True
        except TorngitClientError:
            log.error(
                "Error creating/updating PR comment",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=self.commit_report.external_id,
                    pullid=pullid,
                ),
            )
            return False

    def _build_message(
        self, pull: EnrichedPull, comparison: BundleAnalysisComparison
    ) -> str:
        bundle_changes = comparison.bundle_changes()

        bundle_rows = self._create_bundle_rows(
            bundle_changes=bundle_changes, comparison=comparison
        )
        return self._write_lines(
            bundle_rows=bundle_rows,
            total_size_delta=comparison.total_size_delta,
            pull=pull,
        )

    def _create_bundle_rows(
        self,
        bundle_changes: Iterator[BundleChange],
        comparison: BundleAnalysisComparison,
    ) -> Tuple[List[BundleRows], int]:
        bundle_rows = []

        # Calculate bundle change data in one loop since bundle_changes is a generator
        for bundle_change in bundle_changes:
            # Define row table data
            bundle_name = bundle_change.bundle_name
            if bundle_change.change_type == BundleChange.ChangeType.REMOVED:
                size = "(removed)"
            else:
                head_bundle_report = comparison.head_report.bundle_report(bundle_name)
                size = self._bytes_readable(head_bundle_report.total_size())

            change_size = bundle_change.size_delta
            icon = ""
            if change_size > 0:
                icon = ":arrow_up:"
            elif change_size < 0:
                icon = ":arrow_down:"

            bundle_rows.append(
                BundleRows(
                    bundle_name=bundle_name,
                    size=size,
                    change=f"{self._bytes_readable(change_size)} {icon}",
                )
            )

        return bundle_rows

    def _write_lines(
        self, bundle_rows: List[BundleRows], total_size_delta: int, pull: EnrichedPull
    ) -> str:
        # Write lines
        pull_url = get_bundle_analysis_pull_url(pull=pull.database_pull)

        lines = [
            f"## [Bundle]({pull_url}) Report",
            "",
        ]

        if total_size_delta == 0:
            lines.append("Bundle size has no change :white_check_mark:")
            return "\n".join(lines)

        bundles_total_size = self._bytes_readable(total_size_delta)
        if total_size_delta > 0:
            lines.append(
                f"Changes will increase total bundle size by {bundles_total_size} :arrow_up:"
            )
        else:
            lines.append(
                f"Changes will decrease total bundle size by {bundles_total_size} :arrow_down:"
            )
        lines.append("")

        # table of bundles
        lines += [
            "| Bundle name | Size | Change |",
            "| ----------- | ---- | ------ |",
        ]
        for bundle_row in bundle_rows:
            lines.append(
                f"| {bundle_row.bundle_name} | {bundle_row.size} | {bundle_row.change} |"
            )

        return "\n".join(lines)

    def _bytes_readable(self, bytes: int) -> str:
        # TODO: this could maybe be a helper method in `shared`

        bytes = abs(bytes)

        if bytes < 1000:
            bytes = round(bytes, 2)
            return f"{bytes} bytes"

        kilobytes = bytes / 1000
        if kilobytes < 1000:
            kilobytes = round(kilobytes, 2)
            return f"{kilobytes}kB"

        megabytes = kilobytes / 1000
        if megabytes < 1000:
            megabytes = round(megabytes, 2)
            return f"{megabytes}MB"

        gigabytes = round(megabytes / 1000, 2)
        return f"{gigabytes}GB"
