import sentry_sdk
from shared.reports.readonly import ReadOnlyReport

from services.comparison import ComparisonContext, ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.report import ReportService


@sentry_sdk.trace
def get_comparison_proxy(
    comparison, current_yaml, installation_name_to_use: str | None = None
):
    compare_commit = comparison.compare_commit
    base_commit = comparison.base_commit
    report_service = ReportService(
        current_yaml, gh_app_installation_name=installation_name_to_use
    )
    base_report = report_service.get_existing_report_for_commit(
        base_commit, report_class=ReadOnlyReport
    )
    compare_report = report_service.get_existing_report_for_commit(
        compare_commit, report_class=ReadOnlyReport
    )
    # No access to the PR so we have to assume the base commit did not need
    # to be adjusted.
    patch_coverage_base_commitid = base_commit.commitid
    return ComparisonProxy(
        Comparison(
            head=FullCommit(commit=compare_commit, report=compare_report),
            project_coverage_base=FullCommit(commit=base_commit, report=base_report),
            patch_coverage_base_commitid=patch_coverage_base_commitid,
            enriched_pull=None,
        ),
        context=ComparisonContext(gh_app_installation_name=installation_name_to_use),
    )
