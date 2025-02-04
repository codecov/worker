import logging

from asgiref.sync import async_to_sync
from shared.components import Component
from shared.utils.enums import TaskConfigGroup
from shared.yaml import UserYaml
from sqlalchemy.orm import Session

from app import celery_app
from database.models import CompareCommit, CompareComponent
from helpers.github_installation import get_installation_name_for_owner_for_task
from services.comparison import ComparisonProxy, FilteredComparison
from services.comparison_utils import get_comparison_proxy
from services.report import ReportService
from services.yaml import get_current_yaml, get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

task_name = (
    f"app.tasks.{TaskConfigGroup.compute_comparison.value}.ComputeComponentComparison"
)


def compute_component_comparison(
    db_session: Session,
    comparison: CompareCommit,
    comparison_proxy: ComparisonProxy,
    component: Component,
):
    component_comparison = (
        db_session.query(CompareComponent)
        .filter_by(
            commit_comparison_id=comparison.id,
            component_id=component.component_id,
        )
        .first()
    )
    if not component_comparison:
        component_comparison = CompareComponent(
            commit_comparison=comparison,
            component_id=component.component_id,
        )

    # filter comparison by component
    head_report = comparison_proxy.comparison.head.report
    flags = component.get_matching_flags(head_report.flags.keys())
    filtered: FilteredComparison = comparison_proxy.get_filtered_comparison(
        flags=flags, path_patterns=component.paths
    )

    # component comparison totals
    component_comparison.base_totals = (
        filtered.project_coverage_base.report.totals.asdict()
    )
    component_comparison.head_totals = filtered.head.report.totals.asdict()
    diff = comparison_proxy.get_diff()
    if diff:
        patch_totals = filtered.head.report.apply_diff(diff)
        if patch_totals:
            component_comparison.patch_totals = patch_totals.asdict()

    db_session.add(component_comparison)
    db_session.flush()


class ComputeComponentComparisonTask(BaseCodecovTask, name=task_name):
    def run_impl(
        self,
        db_session: Session,
        comparison_id: int,
        component_id: str,
        *args,
        **kwargs,
    ):
        comparison: CompareCommit = db_session.query(CompareCommit).get(comparison_id)
        repo = comparison.compare_commit.repository

        log_extra = dict(
            comparison_id=comparison_id,
            repoid=repo.repoid,
            commit=comparison.compare_commit.commitid,
        )
        log.info("Computing component comparison", extra=log_extra)

        current_yaml = get_repo_yaml(repo)
        installation_name_to_use = get_installation_name_for_owner_for_task(
            self.name, repo.owner
        )
        report_service = ReportService(
            current_yaml, gh_app_installation_name=installation_name_to_use
        )
        comparison_proxy = get_comparison_proxy(comparison, report_service)
        head_commit = comparison_proxy.comparison.head.commit

        yaml: UserYaml = async_to_sync(get_current_yaml)(
            head_commit, comparison_proxy.repository_service
        )

        components = yaml.get_components()

        component_dict = {c.component_id: c for c in components}
        compute_component_comparison(
            db_session, comparison, comparison_proxy, component_dict[component_id]
        )

        log.info("Finished computing component comparison", extra=log_extra)


RegisteredComputeComponentComparisonTask = celery_app.register_task(
    ComputeComponentComparisonTask()
)
compute_component_comparison_task = celery_app.tasks[
    RegisteredComputeComponentComparisonTask.name
]
