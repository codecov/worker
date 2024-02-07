import logging
from datetime import datetime
from typing import Iterable, Mapping, Optional

from shared.reports.readonly import ReadOnlyReport
from sqlalchemy.dialects.postgresql import insert

from database.models import Commit, Dataset, Measurement, MeasurementName
from database.models.core import Repository
from database.models.reports import RepositoryFlag
from helpers.timeseries import backfill_max_batch_size, timeseries_enabled
from services.report import ReportService
from services.yaml import get_repo_yaml

log = logging.getLogger(__name__)


def save_commit_measurements(
    commit: Commit, dataset_names: Iterable[str] = None
) -> None:
    if not timeseries_enabled():
        return

    if dataset_names is None:
        dataset_names = [
            dataset.name for dataset in repository_datasets_query(commit.repository)
        ]
    if len(dataset_names) == 0:
        return

    current_yaml = get_repo_yaml(commit.repository)
    report_service = ReportService(current_yaml)
    report = report_service.get_existing_report_for_commit(
        commit, report_class=ReadOnlyReport
    )

    if report is None:
        return

    db_session = commit.get_db_session()

    if MeasurementName.coverage.value in dataset_names:
        if report.totals.coverage is not None:
            command = insert(Measurement.__table__).values(
                name=MeasurementName.coverage.value,
                owner_id=commit.repository.ownerid,
                repo_id=commit.repoid,
                measurable_id=f"{commit.repoid}",
                branch=commit.branch,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                value=float(report.totals.coverage),
            )
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

    if MeasurementName.flag_coverage.value in dataset_names:
        flag_ids = repository_flag_ids(commit.repository)
        measurements = []

        for flag_name, flag in report.flags.items():
            if flag.totals.coverage is not None:
                flag_id = flag_ids.get(flag_name)
                if not flag_id:
                    log.warning(
                        "Repository flag not found.  Created repository flag.",
                        extra=dict(repoid=commit.repoid, flag_name=flag_name),
                    )
                    repo_flag = RepositoryFlag(
                        repository_id=commit.repoid,
                        flag_name=flag_name,
                    )
                    db_session.add(repo_flag)
                    db_session.flush()
                    flag_id = repo_flag.id

                measurements.append(
                    dict(
                        name=MeasurementName.flag_coverage.value,
                        owner_id=commit.repository.ownerid,
                        repo_id=commit.repoid,
                        measurable_id=f"{flag_id}",
                        branch=commit.branch,
                        commit_sha=commit.commitid,
                        timestamp=commit.timestamp,
                        value=float(flag.totals.coverage),
                    )
                )

        if len(measurements) > 0:
            log.info(
                "Upserting flag coverage measurements",
                extra=dict(
                    repoid=commit.repoid,
                    commit_id=commit.id_,
                    count=len(measurements),
                ),
            )
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

    if MeasurementName.component_coverage.value in dataset_names:
        components = current_yaml.get_components()
        if components:
            measurements = []

            for component in components:
                if component.paths or component.flag_regexes:
                    report_and_component_matching_flags = component.get_matching_flags(
                        report.flags.keys()
                    )
                    filtered_report = report.filter(
                        flags=report_and_component_matching_flags, paths=component.paths
                    )

                    if filtered_report.totals.coverage is not None:
                        measurements.append(
                            dict(
                                name=MeasurementName.component_coverage.value,
                                owner_id=commit.repository.ownerid,
                                repo_id=commit.repoid,
                                branch=commit.branch,
                                commit_sha=commit.commitid,
                                timestamp=commit.timestamp,
                                measurable_id=f"{component.component_id}",
                                value=float(filtered_report.totals.coverage),
                            )
                        )

            if len(measurements) > 0:
                log.info(
                    "Upserting component coverage measurements",
                    extra=dict(
                        repoid=commit.repoid,
                        commit_id=commit.id_,
                        count=len(measurements),
                    ),
                )
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


def repository_commits_query(
    repository: Repository,
    start_date: datetime,
    end_date: datetime,
) -> Iterable[Commit]:
    db_session = repository.get_db_session()

    commits = (
        db_session.query(Commit.id_)
        .filter(
            Commit.repoid == repository.repoid,
            Commit.timestamp >= start_date,
            Commit.timestamp <= end_date,
        )
        .order_by(Commit.timestamp.desc())
        .yield_per(100)
    )

    return commits


def repository_datasets_query(
    repository: Repository, backfilled: Optional[bool] = None
) -> Iterable[Dataset]:
    db_session = repository.get_db_session()

    datasets = db_session.query(Dataset.name).filter_by(repository_id=repository.repoid)
    if backfilled is not None:
        datasets = datasets.filter_by(backfilled=backfilled)

    return datasets


def repository_flag_ids(repository: Repository) -> Mapping[str, int]:
    db_session = repository.get_db_session()

    repo_flags = (
        db_session.query(RepositoryFlag).filter_by(repository=repository).yield_per(100)
    )

    return {repo_flag.flag_name: repo_flag.id for repo_flag in repo_flags}


def backfill_batch_size(repository: Repository) -> int:
    db_session = repository.get_db_session()

    flag_count = (
        db_session.query(RepositoryFlag)
        .filter_by(repository_id=repository.repoid)
        .count()
    )

    flag_count = max(flag_count, 1)
    batch_size = int(backfill_max_batch_size() / flag_count)
    return max(batch_size, 1)


def delete_repository_data(repository: Repository):
    db_session = repository.get_db_session()
    db_session.query(Dataset).filter_by(repository_id=repository.repoid).delete()
    db_session.query(Measurement).filter_by(
        owner_id=repository.ownerid,
        repo_id=repository.repoid,
    ).delete()
