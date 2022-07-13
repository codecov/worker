import logging
from typing import Dict, List

from shared.celery_config import compute_comparison_task_name
from shared.helpers.flag import Flag
from shared.reports.readonly import ReadOnlyReport
from shared.torngit.exceptions import TorngitRateLimitError
from shared.yaml import UserYaml

from app import celery_app
from database.enums import CompareCommitError, CompareCommitState
from database.models import CompareCommit, CompareFlag
from database.models.core import Commit
from database.models.reports import ReportLevelTotals, RepositoryFlag
from helpers.metrics import metrics
from services.archive import ArchiveService
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.report import ReportService
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ComputeComparisonTask(BaseCodecovTask):
    name = compute_comparison_task_name

    async def run_async(self, db_session, comparison_id, *args, **kwargs):
        comparison = db_session.query(CompareCommit).get(comparison_id)
        repo = comparison.compare_commit.repository
        log_extra = dict(comparison_id=comparison_id, repoid=repo.repoid)
        log.info("Computing comparison", extra=log_extra)
        current_yaml = self.get_yaml_commit(comparison.compare_commit)

        with metrics.timer(f"{self.metrics_prefix}.get_comparison_proxy"):
            comparison_proxy = await self.get_comparison_proxy(comparison, current_yaml)
        if not comparison_proxy.has_base_report():
            comparison.error = CompareCommitError.missing_base_report.value
        elif not comparison_proxy.has_head_report():
            comparison.error = CompareCommitError.missing_head_report.value
        else:
            comparison.error = None

        if comparison.error:
            comparison.state = CompareCommitState.error.value
            log.warn("Compute comparison failed, %s", comparison.error, extra=log_extra)
            return {"successful": False}

        try:
            with metrics.timer(f"{self.metrics_prefix}.serialize_impacted_files") as tm:
                impacted_files = await self.serialize_impacted_files(comparison_proxy)
        except TorngitRateLimitError:
            log.warning(
                "Unable to compute comparison due to rate limit error",
                extra=dict(
                    comparison_id=comparison_id, repoid=comparison.compare_commit.repoid
                ),
            )
            return {"successful": False}
        log.info("Files impact calculated", extra=dict(timing_ms=tm.ms, **log_extra))
        with metrics.timer(f"{self.metrics_prefix}.store_results"):
            path = self.store_results(comparison, impacted_files)

        comparison.report_storage_path = path
        comparison.patch_totals = impacted_files.get("changes_summary").get(
            "patch_totals"
        )
        comparison.state = CompareCommitState.processed.value
        log.info("Computing comparison successful", extra=log_extra)
        db_session.commit()

        await self.compute_flag_comparison(
            db_session, comparison, comparison_proxy, current_yaml
        )
        return {"successful": True}

    async def compute_flag_comparison(
        self, db_session, comparison, comparison_proxy, current_yaml
    ):
        log_extra = dict(comparison_id=comparison.id, current_yaml=current_yaml)
        log.info("Computing flag comparisons", extra=log_extra)
        head_report_flags = await self.get_flags_from_report(commit=comparison.compare_commit, current_yaml=current_yaml)
        if not head_report_flags:
            log.info("Head report does not have any flags", extra=log_extra)
            return
        await self.create_or_update_flag_comparisons(
            db_session, head_report_flags, comparison, comparison_proxy, current_yaml
        )

    async def get_flags_from_report(
        self, commit: Commit, current_yaml: UserYaml
    ) -> List[Flag]:
        report_service = ReportService(current_yaml)
        report = report_service.get_existing_report_for_commit(
            commit, report_class=ReadOnlyReport
        )
        return report.flags

    async def create_or_update_flag_comparisons(
        self,
        db_session,
        head_report_flags: List[Flag],
        comparison: CompareCommit,
        comparison_proxy: ComparisonProxy,
        current_yaml
    ):
        base_report_flags = await self.get_flags_from_report(commit=comparison.base_commit, current_yaml=current_yaml)
        print("hereee")
        print(base_report_flags)
        print(base_report_flags.__dict__)
        flag_comparisons = (
            db_session.query(CompareFlag)
            .filter_by(commit_comparison_id=comparison.id)
            .all()
        )
        if not flag_comparisons:
            log.info(
                "No previous flag comparisons for commit_comparison_id %s. Storing flag comparisons",
                comparison.id,
            )
            await self.create_and_store_flag_comparisons(
                db_session, head_report_flags, base_report_flags, comparison, comparison_proxy
            )
        else:
            log.info(
                "Existing flag comparisons for commit_comparison_id %s. Adding or updating flag comparisons",
                comparison.id,
            )
            await self.update_or_add_flag_comparisons_for_new_upload(
                db_session, head_report_flags, base_report_flags, comparison, comparison_proxy
            )

    async def create_and_store_flag_comparisons(
        self,
        db_session,
        head_report_flags: List[Flag],
        base_report_flags: List[Flag],
        comparison: CompareCommit,
        comparison_proxy: ComparisonProxy,
    ):
        for flag_name, flag_obj in head_report_flags.items():
            head_totals, patch_totals = await self.get_flag_comparison_totals(
                flag_obj, comparison_proxy
            )
            repositoryflag = (
                db_session.query(RepositoryFlag)
                .filter_by(
                    flag_name=flag_name,
                    repository_id=comparison.compare_commit.repository.repoid,
                )
                .first()
            )
            self.store_flag_comparison(
                db_session,
                comparison,
                repositoryflag,
                head_totals,
                patch_totals,
            )
        log.info("%s flag comparisons stored successfully", len(head_report_flags))

    async def update_or_add_flag_comparisons_for_new_upload(
        self,
        db_session,
        head_report_flags: List[Flag],
        base_report_flags: List[Flag],
        comparison: CompareCommit,
        comparison_proxy: ComparisonProxy,
    ):
        for flag_name, flag_obj in head_report_flags.items():
            repositoryflag = (
                db_session.query(RepositoryFlag)
                .filter_by(
                    flag_name=flag_name,
                    repository_id=comparison.compare_commit.repository.repoid,
                )
                .first()
            )
            flag_comparison_entry = (
                db_session.query(CompareFlag)
                .filter_by(
                    commit_comparison_id=comparison.id,
                    repositoryflag_id=repositoryflag.id,
                )
                .first()
            )

            if not flag_comparison_entry:
                log.info("Adding new flag comparison")
                head_totals, patch_totals = await self.get_flag_comparison_totals(
                    flag_obj, comparison_proxy
                )
                self.store_flag_comparison(
                    db_session,
                    comparison,
                    flag_name,
                    head_totals,
                    patch_totals,
                )
            else:
                log.info("Updating totals for existing flag comparison entry")
                head_totals, patch_totals = await self.get_flag_comparison_totals(
                    flag_obj, comparison_proxy
                )
                flag_comparison_entry.head_totals = head_totals
                flag_comparison_entry.patch_totals = patch_totals
        log.info("%s flag comparisons stored successfully", len(head_report_flags))

    async def get_flag_comparison_totals(
        self, flag_obj: Flag, comparison_proxy: ComparisonProxy
    ):
        filtered_flag_report = flag_obj.report
        head_totals = filtered_flag_report.totals
        comparison_diff = await comparison_proxy.get_diff()
        patch_totals = filtered_flag_report.apply_diff(comparison_diff)
        return head_totals.asdict(), patch_totals.asdict()

    def store_flag_comparison(
        self,
        db_session,
        comparison: CompareCommit,
        repositoryflag: RepositoryFlag,
        head_totals: Dict[str, ReportLevelTotals],
        patch_totals: Dict[str, ReportLevelTotals],
    ):
        flag_comparison = CompareFlag(
            commit_comparison=comparison,
            repositoryflag=repositoryflag,
            patch_totals=patch_totals,
            head_totals=head_totals,
        )
        db_session.add(flag_comparison)
        db_session.flush()

    def get_yaml_commit(self, commit):
        return get_repo_yaml(commit.repository)

    async def get_comparison_proxy(self, comparison, current_yaml):
        compare_commit = comparison.compare_commit
        base_commit = comparison.base_commit
        report_service = ReportService(current_yaml)
        base_report = report_service.get_existing_report_for_commit(
            base_commit, report_class=ReadOnlyReport
        )
        compare_report = report_service.get_existing_report_for_commit(
            compare_commit, report_class=ReadOnlyReport
        )
        return ComparisonProxy(
            Comparison(
                head=FullCommit(commit=compare_commit, report=compare_report),
                enriched_pull=None,
                base=FullCommit(commit=base_commit, report=base_report),
            )
        )

    async def serialize_impacted_files(self, comparison_proxy):
        return await comparison_proxy.get_impacted_files()

    def store_results(self, comparison, impacted_files):
        repository = comparison.compare_commit.repository
        storage_service = ArchiveService(repository)
        return storage_service.write_computed_comparison(comparison, impacted_files)


RegisteredComputeComparisonTask = celery_app.register_task(ComputeComparisonTask())
compute_comparison_task = celery_app.tasks[RegisteredComputeComparisonTask.name]
