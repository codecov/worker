import logging
from typing import Sequence

from celery import group
from shared.celery_config import timeseries_save_commit_measurements_task_name
from shared.reports.readonly import ReadOnlyReport
from sqlalchemy.orm import Session

from app import celery_app
from database.models import Commit, MeasurementName
from rollouts import PARALLEL_COMPONENT_COMPARISON
from services.report import ReportService
from services.timeseries import (
    maybe_upsert_coverage_measurement,
    maybe_upsert_flag_measurements,
    repository_datasets_query,
    upsert_components_measurements,
)
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask
from tasks.upsert_component import upsert_component_task

log = logging.getLogger(__name__)


def save_commit_measurements(commit: Commit, dataset_names: Sequence[str]) -> None:
    if len(dataset_names) == 0:
        log.debug(
            "No datasets found for commit",
            extra=dict(commitid=commit.commitid, repoid=commit.repoid),
        )
        return

    current_yaml = get_repo_yaml(commit.repository)
    report_service = ReportService(current_yaml)
    report = report_service.get_existing_report_for_commit(
        commit, report_class=ReadOnlyReport
    )

    if report is None:
        log.warning(
            "No report found for commit",
            extra=dict(commitid=commit.commitid, repoid=commit.repoid),
        )
        return

    db_session = commit.get_db_session()

    maybe_upsert_coverage_measurement(commit, dataset_names, db_session, report)
    if MeasurementName.component_coverage.value in dataset_names:
        components = current_yaml.get_components()
        if components:
            if PARALLEL_COMPONENT_COMPARISON.check_value(commit.repository.repoid):
                task_signatures = []
                components = current_yaml.get_components()
                for component in components:
                    if component.paths or component.flag_regexes:
                        report_and_component_matching_flags = (
                            component.get_matching_flags(list(report.flags.keys()))
                        )
                        task_signatures.append(
                            upsert_component_task.s(
                                commit.commitid,
                                commit.repoid,
                                component.component_id,
                                report_and_component_matching_flags,
                                component.paths,
                            )
                        )
                if task_signatures:
                    task_group = group(task_signatures)
                    task_group.apply_async()
            else:
                upsert_components_measurements(commit, current_yaml, db_session, report)

    maybe_upsert_flag_measurements(commit, dataset_names, db_session, report)


class SaveCommitMeasurementsTask(
    BaseCodecovTask, name=timeseries_save_commit_measurements_task_name
):
    def run_impl(
        self,
        db_session: Session,
        commitid: str,
        repoid: int,
        dataset_names: Sequence[str] | None,
        *args,
        **kwargs,
    ):
        log.info(
            "Received save_commit_measurements task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                dataset_names=dataset_names,
                parent_task=self.request.parent_id,
            ),
        )

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )

        if commit is None:
            return {"successful": False, "error": "no_commit_in_db"}

        if dataset_names is None:
            dataset_names = [
                dataset.name for dataset in repository_datasets_query(commit.repository)
            ]
        if len(dataset_names) == 0:
            return

        try:
            # TODO: We should improve on the error handling/logs inside this fn
            save_commit_measurements(commit=commit, dataset_names=dataset_names)
            return {"successful": True}
        except Exception:
            log.exception(
                "An error happened while saving commit measurements",
                extra=dict(commitid=commitid, task_args=args, task_kwargs=kwargs),
            )
            return {"successful": False, "error": "exception"}


RegisteredSaveCommitMeasurementsTask = celery_app.register_task(
    SaveCommitMeasurementsTask()
)
save_commit_measurements_task = celery_app.tasks[
    RegisteredSaveCommitMeasurementsTask.name
]
