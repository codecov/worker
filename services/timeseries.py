import logging

from shared.config import get_config
from shared.reports.readonly import ReadOnlyReport
from sqlalchemy.dialects.postgresql import insert

from database.models import Commit, Measurement, MeasurementName
from database.models.reports import RepositoryFlag
from services.report import ReportService
from services.yaml import get_repo_yaml

log = logging.getLogger(__name__)


def timeseries_enabled() -> bool:
    return get_config("setup", "timeseries", "enabled", default=False)


def save_commit_measurements(commit: Commit) -> None:
    if not timeseries_enabled():
        return

    db_session = commit.get_db_session()

    current_yaml = get_repo_yaml(commit.repository)
    report_service = ReportService(current_yaml)
    report = report_service.get_existing_report_for_commit(
        commit, report_class=ReadOnlyReport
    )

    command = (
        insert(Measurement.__table__)
        .values(
            name=MeasurementName.coverage.value,
            owner_id=commit.repository.ownerid,
            repo_id=commit.repoid,
            flag_id=None,
            branch=commit.branch,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            value=float(report.totals.coverage),
        )
        .on_conflict_do_update(
            index_elements=[
                Measurement.name,
                Measurement.owner_id,
                Measurement.repo_id,
                Measurement.commit_sha,
                Measurement.timestamp,
            ],
            index_where=(Measurement.flag_id.is_(None)),
            set_=dict(
                branch=commit.branch,
                value=float(report.totals.coverage),
            ),
        )
    )
    db_session.execute(command)
    db_session.flush()

    for flag_name, flag in report.flags.items():
        repo_flag = (
            db_session.query(RepositoryFlag)
            .filter_by(
                repository=commit.repository,
                flag_name=flag_name,
            )
            .one_or_none()
        )

        if not repo_flag:
            log.warning(
                "Repository flag not found.  Created repository flag.",
                extra=dict(repo=commit.repoid, flag_name=flag_name),
            )
            repo_flag = RepositoryFlag(
                repository_id=commit.repoid,
                flag_name=flag_name,
            )
            db_session.add(repo_flag)
            db_session.flush()

        command = (
            insert(Measurement.__table__)
            .values(
                name=MeasurementName.flag_coverage.value,
                owner_id=commit.repository.ownerid,
                repo_id=commit.repoid,
                flag_id=repo_flag.id,
                branch=commit.branch,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                value=float(flag.totals.coverage),
            )
            .on_conflict_do_update(
                index_elements=[
                    Measurement.name,
                    Measurement.owner_id,
                    Measurement.repo_id,
                    Measurement.flag_id,
                    Measurement.commit_sha,
                    Measurement.timestamp,
                ],
                index_where=(Measurement.flag_id.isnot(None)),
                set_=dict(
                    branch=commit.branch,
                    value=float(flag.totals.coverage),
                ),
            )
        )
        db_session.execute(command)
        db_session.flush()
