import logging
from datetime import datetime
from typing import TypedDict

from asgiref.sync import async_to_sync
from shared.reports.readonly import ReadOnlyReport
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import celery_app
from database.models import Commit, Measurement, MeasurementName
from helpers.github_installation import get_installation_name_for_owner_for_task
from services.report import ReportService
from services.repository import get_repo_provider_service
from services.yaml import UserYaml, get_current_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class MeasurementDict(TypedDict):
    name: str
    owner_id: int
    repo_id: int
    measurable_id: str
    branch: str
    commit_sha: str
    timestamp: datetime
    value: float


def create_measurement_dict(
    name: str, commit: Commit, measurable_id: str, value: float
) -> MeasurementDict:
    return {
        "name": name,
        "owner_id": commit.repository.ownerid,
        "repo_id": commit.repoid,
        "measurable_id": measurable_id,
        "branch": commit.branch,
        "commit_sha": commit.commitid,
        "timestamp": commit.timestamp,
        "value": value,
    }


def upsert_measurements(
    db_session: Session, measurements: list[MeasurementDict]
) -> None:
    command = insert(Measurement.__table__).values(measurements)
    command = command.on_conflict_do_update(
        index_elements=[
            Measurement.name,
            Measurement.owner_id,
            Measurement.repo_id,
            Measurement.measurable_id,
            Measurement.commit_sha,
            Measurement.timestamp,
        ],
        set_=dict(
            branch=command.excluded.branch,
            value=command.excluded.value,
        ),
    )
    db_session.execute(command)
    db_session.flush()


class UpsertComponentTask(BaseCodecovTask):
    def run_impl(
        self,
        db_session: Session,
        commitid: str,
        repoid: int,
        component_id: str,
        *args,
        **kwargs,
    ):
        log.info("Upserting component", extra=dict(commitid=commitid, repoid=repoid))

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )

        installation_name_to_use = get_installation_name_for_owner_for_task(
            self.name, commit.repository.owner
        )

        repository_service = get_repo_provider_service(
            commit.repository, installation_name_to_use=installation_name_to_use
        )

        yaml: UserYaml = async_to_sync(get_current_yaml)(commit, repository_service)

        components = yaml.get_components()

        report_service = ReportService(yaml)
        report = report_service.get_existing_report_for_commit(
            commit, report_class=ReadOnlyReport
        )

        if report is None:
            log.warning(
                "Upsert Component: No report found for commit",
                extra=dict(
                    component_id=component_id,
                    commitid=commitid,
                    repoid=repoid,
                ),
            )
            return

        component_dict = {component.component_id: component for component in components}

        component = component_dict[component_id]

        if component.paths or component.flag_regexes:
            report_and_component_matching_flags = component.get_matching_flags(
                list(report.flags.keys())
            )
            filtered_report = report.filter(
                flags=report_and_component_matching_flags, paths=component.paths
            )
            if filtered_report.totals.coverage is not None:
                measurement = create_measurement_dict(
                    MeasurementName.component_coverage.value,
                    commit,
                    measurable_id=f"{component.component_id}",
                    value=float(filtered_report.totals.coverage),
                )

                upsert_measurements(db_session, [measurement])


registered_task = celery_app.register_task(UpsertComponentTask())
upsert_component_task = celery_app.tasks[registered_task.name]
