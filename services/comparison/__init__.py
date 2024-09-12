import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import sentry_sdk
from shared.reports.changes import get_changes_using_rust, run_comparison_using_rust
from shared.reports.types import Change, ReportTotals
from shared.torngit.exceptions import (
    TorngitClientGeneralError,
)
from shared.utils.sessions import SessionType

from database.enums import CompareCommitState, TestResultsProcessingError
from database.models import CompareCommit
from helpers.metrics import metrics
from services.archive import ArchiveService
from services.comparison.changes import get_changes
from services.comparison.overlays import get_overlay
from services.comparison.types import Comparison, FullCommit, ReportUploadedCount
from services.repository import get_repo_provider_service

log = logging.getLogger(__name__)


@dataclass
class ComparisonContext(object):
    """Extra information not necessarily related to coverage that may affect notifications"""

    all_tests_passed: bool | None = None
    test_results_error: TestResultsProcessingError | None = None
    gh_app_installation_name: str | None = None
    gh_is_using_codecov_commenter: bool = False


class ComparisonProxy(object):
    """The idea of this class is to produce a wrapper around Comparison with functionalities that
        are useful to the notifications context.

        What ComparisonProxy aims to do is to provide a bunch of common calculations (like
            get_changes and get_diff) with a specific set of assumptions very fit for the
            notification use-cases (like the one that we should use the head commit repository
            to fetch data, or that there is even a repository we can fetch data from,
            and that whatever information is fetched at first would not change).

        This is not really meant for other places where a comparison might be used (
            like when one really only needs the actual in-database and in-report information).
            A pure Comparison should be used for those cases

    Attributes:
        comparison (Comparison): The original comparison we want to wrap and proxy
        context (ComparisonContext | None): Other information not coverage-related that may affect notifications
    """

    def __init__(
        self, comparison: Comparison, context: Optional[ComparisonContext] = None
    ):
        self.comparison = comparison
        self._repository_service = None
        self._adjusted_base_diff = None
        self._original_base_diff = None
        self._patch_totals = None
        self._changes = None
        self._existing_statuses = None
        self._behind_by = None
        self._branch = None
        self._diff_lock = asyncio.Lock()
        self._changes_lock = asyncio.Lock()
        self._existing_statuses_lock = asyncio.Lock()
        self._behind_by_lock = asyncio.Lock()
        self._archive_service = None
        self._overlays = {}
        self.context = context or ComparisonContext()
        self._cached_reports_uploaded_per_flag: List[ReportUploadedCount] | None = None

    def get_archive_service(self):
        if self._archive_service is None:
            self._archive_service = ArchiveService(
                self.comparison.project_coverage_base.commit.repository
            )
        return self._archive_service

    @metrics.timer("internal.services.comparison.get_filtered_comparison")
    def get_filtered_comparison(self, flags, path_patterns):
        if not flags and not path_patterns:
            return self
        return FilteredComparison(self, flags=flags, path_patterns=path_patterns)

    @property
    def repository_service(self):
        if self._repository_service is None:
            self._repository_service = get_repo_provider_service(
                self.comparison.head.commit.repository,
                installation_name_to_use=self.context.gh_app_installation_name,
            )
        return self._repository_service

    def has_project_coverage_base_report(self):
        return self.comparison.has_project_coverage_base_report()

    def has_head_report(self):
        return self.comparison.has_head_report()

    @property
    def head(self):
        return self.comparison.head

    @property
    def project_coverage_base(self):
        return self.comparison.project_coverage_base

    @property
    def enriched_pull(self):
        return self.comparison.enriched_pull

    @property
    def pull(self):
        return self.comparison.pull

    async def get_diff(self, use_original_base=False):
        async with self._diff_lock:
            head = self.comparison.head.commit
            base = self.comparison.project_coverage_base.commit
            patch_coverage_base_commitid = self.comparison.patch_coverage_base_commitid

            # If the original and adjusted bases are the same commit, then if we
            # already fetched the diff for one we can return it for the other.
            bases_match = patch_coverage_base_commitid == (
                base.commitid if base else ""
            )

            populate_original_base_diff = use_original_base and (
                not self._original_base_diff
            )
            populate_adjusted_base_diff = (not use_original_base) and (
                not self._adjusted_base_diff
            )
            if populate_original_base_diff:
                if bases_match and self._adjusted_base_diff:
                    self._original_base_diff = self._adjusted_base_diff
                elif patch_coverage_base_commitid is not None:
                    pull_diff = await self.repository_service.get_compare(
                        patch_coverage_base_commitid, head.commitid, with_commits=False
                    )
                    self._original_base_diff = pull_diff["diff"]
                else:
                    return None
            elif populate_adjusted_base_diff:
                if bases_match and self._original_base_diff:
                    self._adjusted_base_diff = self._original_base_diff
                elif base is not None:
                    pull_diff = await self.repository_service.get_compare(
                        base.commitid, head.commitid, with_commits=False
                    )
                    self._adjusted_base_diff = pull_diff["diff"]
                else:
                    return None

            if use_original_base:
                return self._original_base_diff
            else:
                return self._adjusted_base_diff

    async def get_changes(self) -> Optional[List[Change]]:
        # Just make sure to not cause a deadlock between this and get_diff
        async with self._changes_lock:
            if self._changes is None:
                diff = await self.get_diff()
                with metrics.timer(
                    "internal.worker.services.comparison.changes.get_changes_python"
                ):
                    self._changes = get_changes(
                        self.comparison.project_coverage_base.report,
                        self.comparison.head.report,
                        diff,
                    )
                if (
                    self.comparison.project_coverage_base.report is not None
                    and self.comparison.head.report is not None
                    and self.comparison.project_coverage_base.report.rust_report
                    is not None
                    and self.comparison.head.report.rust_report is not None
                ):
                    with metrics.timer(
                        "internal.worker.services.comparison.changes.get_changes_rust"
                    ):
                        rust_changes = get_changes_using_rust(
                            self.comparison.project_coverage_base.report,
                            self.comparison.head.report,
                            diff,
                        )
                    original_paths = set([c.path for c in self._changes])
                    new_paths = set([c.path for c in rust_changes])
                    if original_paths != new_paths:
                        only_on_new = sorted(new_paths - original_paths)
                        only_on_original = sorted(original_paths - new_paths)
                        log.info(
                            "There are differences between python changes and rust changes",
                            extra=dict(
                                only_on_new=only_on_new[:100],
                                only_on_original=only_on_original[:100],
                                repoid=self.head.commit.repoid,
                            ),
                        )
            return self._changes

    @sentry_sdk.trace
    async def get_patch_totals(self) -> ReportTotals | None:
        """Returns the patch coverage for the comparison.

        Patch coverage refers to looking at the coverage in HEAD report filtered by the git diff HEAD..BASE.
        """
        if self._patch_totals:
            return self._patch_totals
        diff = await self.get_diff(use_original_base=True)
        self._patch_totals = self.head.report.apply_diff(diff)
        return self._patch_totals

    async def get_behind_by(self):
        async with self._behind_by_lock:
            if self._behind_by is None:
                if not getattr(
                    self.comparison.project_coverage_base.commit, "commitid", None
                ):
                    log.info(
                        "Comparison base commit does not have commitid, unable to get behind_by"
                    )
                    return None

                provider_pull = self.comparison.enriched_pull.provider_pull
                if provider_pull is None:
                    log.info(
                        "Comparison does not have provider pull request information, unable to get behind_by"
                    )
                    return None
                branch_to_get = provider_pull["base"]["branch"]
                if self._branch is None:
                    try:
                        branch_response = await self.repository_service.get_branch(
                            branch_to_get
                        )
                    except TorngitClientGeneralError:
                        log.warning(
                            "Unable to fetch base branch from Git provider",
                            extra=dict(
                                branch=branch_to_get,
                            ),
                        )
                        return None
                    except KeyError:
                        log.warning(
                            "Error fetching base branch from Git provider",
                            extra=dict(
                                branch=branch_to_get,
                            ),
                        )
                        return None
                    self._branch = branch_response

                distance = await self.repository_service.get_distance_in_commits(
                    self._branch["sha"],
                    self.comparison.project_coverage_base.commit.commitid,
                    with_commits=False,
                )
                self._behind_by = distance["behind_by"]
                self.enriched_pull.database_pull.behind_by = distance["behind_by"]
                self.enriched_pull.database_pull.behind_by_commit = distance[
                    "behind_by_commit"
                ]
        return self._behind_by

    def all_tests_passed(self):
        return self.context is not None and self.context.all_tests_passed

    def test_results_error(self):
        return self.context is not None and self.context.test_results_error

    async def get_existing_statuses(self):
        async with self._existing_statuses_lock:
            if self._existing_statuses is None:
                self._existing_statuses = (
                    await self.repository_service.get_commit_statuses(
                        self.head.commit.commitid
                    )
                )
            return self._existing_statuses

    def get_overlay(self, overlay_type, **kwargs):
        if overlay_type not in self._overlays:
            self._overlays[overlay_type] = get_overlay(overlay_type, self, **kwargs)
        return self._overlays[overlay_type]

    async def get_impacted_files(self):
        files_in_diff = await self.get_diff()
        return run_comparison_using_rust(
            self.comparison.project_coverage_base.report,
            self.comparison.head.report,
            files_in_diff,
        )

    def get_reports_uploaded_count_per_flag(self) -> List[ReportUploadedCount]:
        """This function counts how many reports (by flag) the BASE and HEAD commit have."""
        if self._cached_reports_uploaded_per_flag:
            # Reports may have many sessions, so it's useful to memoize this function
            return self._cached_reports_uploaded_per_flag
        if not self.has_head_report() or not self.has_project_coverage_base_report():
            log.warning(
                "Can't calculate diff in uploads. Missing some report",
                extra=dict(
                    has_head_report=self.has_head_report(),
                    has_project_base_report=self.has_project_coverage_base_report(),
                ),
            )
            return []
        per_flag_dict: Dict[str, ReportUploadedCount] = dict()
        base_report = self.comparison.project_coverage_base.report
        head_report = self.comparison.head.report
        ops = [(base_report, "base_count"), (head_report, "head_count")]
        for curr_report, curr_counter in ops:
            for session in curr_report.sessions.values():
                # We ignore carryforward sessions
                # Because not all commits would upload all flags (potentially)
                # But they are still carried forward
                if session.session_type != SessionType.carriedforward:
                    # It's possible that an upload is done without flags.
                    # In this case we still want to count it in the count, but there's no flag associated to it
                    session_flags = session.flags or [""]
                    for flag in session_flags:
                        dict_value = per_flag_dict.get(flag)
                        if dict_value is None:
                            dict_value = ReportUploadedCount(
                                flag=flag, base_count=0, head_count=0
                            )
                        dict_value[curr_counter] += 1
                        per_flag_dict[flag] = dict_value
        self._cached_reports_uploaded_per_flag = list(per_flag_dict.values())
        return self._cached_reports_uploaded_per_flag

    def get_reports_uploaded_count_per_flag_diff(self) -> List[ReportUploadedCount]:
        """
        Returns the difference, per flag, or reports uploaded in BASE and HEAD

        ❗️ For a difference to be considered there must be at least 1 "uploaded" upload in both
        BASE and HEAD (that is, if all reports for a flag are "carryforward" it's not considered a diff)
        """
        reports_per_flag = self.get_reports_uploaded_count_per_flag()

        def is_valid_diff(obj: ReportUploadedCount):
            if self.comparison.current_yaml:
                flag_config = self.comparison.current_yaml.get_flag_configuration(
                    obj["flag"]
                )
                is_flag_carryforward = (
                    flag_config.get("carryforward", False)
                    if flag_config is not None
                    else False
                )
            else:
                is_flag_carryforward = False
            head_and_base_have_uploads = obj["base_count"] > 0 and obj["head_count"] > 0
            head_or_base_have_uploads = obj["base_count"] > 0 or obj["head_count"] > 0
            return (
                (is_flag_carryforward and head_and_base_have_uploads)
                or (not is_flag_carryforward and head_or_base_have_uploads)
            ) and obj["base_count"] > obj["head_count"]

        per_flag_diff = list(filter(is_valid_diff, reports_per_flag))
        self._cached_reports_uploaded_per_flag = per_flag_diff
        return per_flag_diff


class FilteredComparison(object):
    def __init__(self, real_comparison: ComparisonProxy, *, flags, path_patterns):
        self.flags = flags
        self.path_patterns = path_patterns
        self.real_comparison = real_comparison
        self._patch_totals = None
        self._changes = None
        self.project_coverage_base = FullCommit(
            commit=real_comparison.project_coverage_base.commit,
            report=(
                real_comparison.project_coverage_base.report.filter(
                    flags=flags, paths=path_patterns
                )
                if self.has_project_coverage_base_report()
                else None
            ),
        )
        self.head = FullCommit(
            commit=real_comparison.head.commit,
            report=real_comparison.head.report.filter(flags=flags, paths=path_patterns),
        )
        self._changes_lock = asyncio.Lock()

    async def get_impacted_files(self):
        return await self.real_comparison.get_impacted_files()

    async def get_diff(self, use_original_base=False):
        return await self.real_comparison.get_diff(use_original_base=use_original_base)

    @sentry_sdk.trace
    async def get_patch_totals(self) -> ReportTotals | None:
        """Returns the patch coverage for the comparison.

        Patch coverage refers to looking at the coverage in HEAD report filtered by the git diff HEAD..BASE.
        """
        if self._patch_totals:
            return self._patch_totals
        diff = await self.get_diff(use_original_base=True)
        self._patch_totals = self.head.report.apply_diff(diff)
        return self._patch_totals

    async def get_existing_statuses(self):
        return await self.real_comparison.get_existing_statuses()

    def has_project_coverage_base_report(self):
        return self.real_comparison.has_project_coverage_base_report()

    @property
    def enriched_pull(self):
        return self.real_comparison.enriched_pull

    async def get_changes(self) -> Optional[List[Change]]:
        # Just make sure to not cause a deadlock between this and get_diff
        async with self._changes_lock:
            if self._changes is None:
                diff = await self.get_diff()
                self._changes = get_changes(
                    self.project_coverage_base.report, self.head.report, diff
                )
            return self._changes

    @property
    def pull(self):
        return self.real_comparison.pull


def get_or_create_comparison(db_session, base_commit, compare_commit):
    comparison = (
        db_session.query(CompareCommit)
        .filter_by(base_commit=base_commit, compare_commit=compare_commit)
        .one_or_none()
    )
    if comparison is None:
        comparison = CompareCommit(
            base_commit=base_commit,
            compare_commit=compare_commit,
            state=CompareCommitState.pending.value,
        )
        db_session.add(comparison)
        db_session.flush()
    return comparison
