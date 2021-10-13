import logging

from shared.celery_config import compute_comparison_task_name
from shared.reports.readonly import ReadOnlyReport

from app import celery_app
from database.enums import CompareCommitError, CompareCommitState
from database.models import CompareCommit
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

        with metrics.timer(f"{self.metrics_prefix}.serialize_impacted_files") as tm:
            impacted_files = await self.serialize_impacted_files(comparison_proxy)
        log.info("Files impact calculated", extra=dict(timing_ms=tm.ms, **log_extra))
        with metrics.timer(f"{self.metrics_prefix}.store_results"):
            path = self.store_results(comparison, impacted_files)

        comparison.report_storage_path = path
        comparison.patch_totals = impacted_files.get("changes_summary").get(
            "patch_totals"
        )
        comparison.state = CompareCommitState.processed.value
        log.info("Computing comparison successful", extra=log_extra)
        return {"successful": True}

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
