import logging

from shared.celery_config import compute_comparison_task_name
from shared.reports.readonly import ReadOnlyReport
from shared.reports.types import Change

from app import celery_app
from tasks.base import BaseCodecovTask
from database.models import CompareCommit
from database.enums import CompareCommitState
from helpers.reports import get_totals_from_file_in_reports
from services.archive import ArchiveService
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.report import ReportService
from services.repository import get_repo_provider_service
from services.yaml import get_current_yaml

log = logging.getLogger(__name__)


class ComputeComparisonTask(BaseCodecovTask):
    name = compute_comparison_task_name

    async def run_async(self, db_session, comparison_id, *args, **kwargs):
        comparison = db_session.query(CompareCommit).get(comparison_id)
        repo = comparison.compare_commit.repository
        log_extra = dict(comparison_id=comparison_id, repoid=repo.repoid)
        log.info(f"Computing comparison", extra=log_extra)
        current_yaml = await self.get_yaml_commit(comparison.compare_commit)
        comparison_proxy = await self.get_comparison_proxy(comparison, current_yaml)
        impacted_files = await self.serialize_impacted_files(comparison_proxy)
        path = self.store_results(comparison, impacted_files)
        comparison.report_storage_path = path
        comparison.state = CompareCommitState.processed
        log.info(f"Computing comparison successful", extra=log_extra)
        return {"successful": True}

    async def get_yaml_commit(self, commit):
        repository_service = get_repo_provider_service(commit.repository)
        return await get_current_yaml(commit, repository_service)

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
        impacted_files = await comparison_proxy.get_impacted_files()
        base_report = comparison_proxy.base.report
        head_report = comparison_proxy.head.report
        data = {"changes": [], "diff": []}
        for file in impacted_files["changes"]:
            path = file.path
            before = get_totals_from_file_in_reports(base_report, path)
            after = get_totals_from_file_in_reports(head_report, path)
            data["changes"].append(
                {
                    "path": file.path,
                    "base_totals": before.astuple() if before else None,
                    "compare_totals": after.astuple() if after else None,
                    "patch": file.totals.astuple(),
                    "new": file.new,
                    "deleted": file.deleted,
                    "in_diff": file.in_diff,
                    "old_path": file.old_path,
                }
            )
        for path, file in impacted_files["diff"].items():
            if not file.get("totals"):
                continue
            before = get_totals_from_file_in_reports(base_report, path)
            after = get_totals_from_file_in_reports(head_report, path)
            data["changes"].append(
                {
                    "path": path,
                    "base_totals": before.astuple() if before else None,
                    "compare_totals": after.astuple() if after else None,
                    "patch": file["totals"].astuple(),
                    "new": file.get("type") == "added",
                    "deleted": file.get("type") == "deleted",
                    "in_diff": True,
                    "old_path": file.get("before"),
                }
            )
        return data

    def store_results(self, comparison, impacted_files):
        repository = comparison.compare_commit.repository
        storage_service = ArchiveService(repository)
        return storage_service.write_computed_comparison(comparison, impacted_files)


RegisteredComputeComparisonTask = celery_app.register_task(ComputeComparisonTask())
compute_comparison_task = celery_app.tasks[RegisteredComputeComparisonTask.name]
