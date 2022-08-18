from datetime import datetime, timezone
from time import time

import pytest
from shared.reports.readonly import ReadOnlyReport
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.utils.sessions import Session

from database.models.timeseries import Measurement, MeasurementName
from database.tests.factories import CommitFactory, RepositoryFactory
from database.tests.factories.reports import RepositoryFlagFactory
from database.tests.factories.timeseries import DatasetFactory, MeasurementFactory
from services.timeseries import (
    backfill_batch_size,
    repository_commits_query,
    repository_datasets_query,
    save_commit_measurements,
)


@pytest.fixture
def sample_report():
    report = Report()
    first_file = ReportFile("file_1.go")
    first_file.append(
        1, ReportLine.create(coverage=1, sessions=[[0, 1]], complexity=(10, 2))
    )
    first_file.append(2, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    first_file.append(3, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(5, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(6, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    first_file.append(8, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(9, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(10, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    second_file = ReportFile("file_2.py")
    second_file.append(12, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    second_file.append(
        51, ReportLine.create(coverage="1/2", type="b", sessions=[[0, 1]])
    )
    report.append(first_file)
    report.append(second_file)
    report.add_session(Session(flags=["flag1", "flag2"]))
    return report


@pytest.fixture
def repository(dbsession):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    coverage_dataset = DatasetFactory.create(
        repository_id=repository.repoid,
        name=MeasurementName.coverage.value,
        backfilled=True,
    )
    dbsession.add(coverage_dataset)
    flag_coverage_dataset = DatasetFactory.create(
        repository_id=repository.repoid,
        name=MeasurementName.flag_coverage.value,
        backfilled=False,
    )
    dbsession.add(flag_coverage_dataset)
    dbsession.flush()

    return repository


class TestTimeseriesService(object):
    def test_insert_commit_measurement(
        self, dbsession, sample_report, repository, mocker
    ):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        save_commit_measurements(commit)

        measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.flag_id == None
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 60.0

    def test_save_commit_measurements_no_report(self, dbsession, repository, mocker):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=None,
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        save_commit_measurements(commit)

        measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
            )
            .one_or_none()
        )

        assert measurement is None

    def test_update_commit_measurement(
        self, dbsession, sample_report, repository, mocker
    ):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        measurement = MeasurementFactory.create(
            name=MeasurementName.coverage.value,
            owner_id=commit.repository.ownerid,
            repo_id=commit.repoid,
            flag_id=None,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            branch="testing",
            value=0,
        )
        dbsession.add(measurement)
        dbsession.flush()

        save_commit_measurements(commit)

        measurements = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
            )
            .all()
        )

        assert len(measurements) == 1
        measurement = measurements[0]
        assert measurement.name == MeasurementName.coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.flag_id == None
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 60.0

    def test_commit_measurement_insert_flags(
        self, dbsession, sample_report, repository, mocker
    ):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        repository_flag1 = RepositoryFlagFactory(
            repository=commit.repository, flag_name="flag1"
        )
        dbsession.add(repository_flag1)
        dbsession.flush()

        repository_flag2 = RepositoryFlagFactory(
            repository=commit.repository, flag_name="flag2"
        )
        dbsession.add(repository_flag2)
        dbsession.flush()

        save_commit_measurements(commit)

        measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.flag_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                flag_id=repository_flag1.id,
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.flag_id == repository_flag1.id
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 100.0

        measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.flag_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                flag_id=repository_flag2.id,
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.flag_id == repository_flag2.id
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 100.0

    def test_commit_measurement_update_flags(
        self, dbsession, sample_report, repository, mocker
    ):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        repository_flag1 = RepositoryFlagFactory(
            repository=commit.repository, flag_name="flag1"
        )
        dbsession.add(repository_flag1)
        dbsession.flush()

        repository_flag2 = RepositoryFlagFactory(
            repository=commit.repository, flag_name="flag2"
        )
        dbsession.add(repository_flag2)
        dbsession.flush()

        measurement1 = MeasurementFactory.create(
            name=MeasurementName.flag_coverage.value,
            owner_id=commit.repository.ownerid,
            repo_id=commit.repoid,
            flag_id=repository_flag1.id,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            branch="testing",
            value=0,
        )
        dbsession.add(measurement1)
        dbsession.flush()

        measurement2 = MeasurementFactory.create(
            name=MeasurementName.flag_coverage.value,
            owner_id=commit.repository.ownerid,
            repo_id=commit.repoid,
            flag_id=repository_flag2.id,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            branch="testing",
            value=0,
        )
        dbsession.add(measurement2)
        dbsession.flush()

        save_commit_measurements(commit)

        measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.flag_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                flag_id=repository_flag1.id,
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.flag_id == repository_flag1.id
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 100.0

        measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.flag_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                flag_id=repository_flag2.id,
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.flag_id == repository_flag2.id
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 100.0

    def test_commit_measurement_no_datasets(self, dbsession, mocker):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)

        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        save_commit_measurements(commit)

        assert dbsession.query(Measurement).count() == 0

    def test_repository_commits_query(self, dbsession, repository, mocker):
        commit1 = CommitFactory.create(
            repository=repository,
            timestamp=datetime(2022, 6, 1, 0, 0, 0).replace(tzinfo=timezone.utc),
        )
        dbsession.add(commit1)
        commit2 = CommitFactory.create(
            repository=repository,
            timestamp=datetime(2022, 6, 10, 0, 0, 0).replace(tzinfo=timezone.utc),
        )
        dbsession.add(commit2)
        commit3 = CommitFactory.create(
            repository=repository,
            timestamp=datetime(2022, 6, 17, 0, 0, 0).replace(tzinfo=timezone.utc),
        )
        dbsession.add(commit3)
        commit4 = CommitFactory.create(
            timestamp=datetime(2022, 6, 10, 0, 0, 0).replace(tzinfo=timezone.utc)
        )
        dbsession.add(commit4)
        dbsession.flush()

        commits = repository_commits_query(
            repository,
            start_date=datetime(2022, 6, 1, 0, 0, 0).replace(tzinfo=timezone.utc),
            end_date=datetime(2022, 6, 15, 0, 0, 0).replace(tzinfo=timezone.utc),
        )

        assert len(list(commits)) == 2
        assert commits[0].id_ == commit2.id_
        assert commits[1].id_ == commit1.id_

    def test_repository_datasets_query(self, repository):
        datasets = repository_datasets_query(repository)
        assert [dataset.name for dataset in datasets] == [
            MeasurementName.coverage.value,
            MeasurementName.flag_coverage.value,
        ]

        datasets = repository_datasets_query(repository, backfilled=True)
        assert [dataset.name for dataset in datasets] == [
            MeasurementName.coverage.value,
        ]

        datasets = repository_datasets_query(repository, backfilled=False)
        assert [dataset.name for dataset in datasets] == [
            MeasurementName.flag_coverage.value,
        ]

    def test_backfill_batch_size(self, repository):
        batch_size = backfill_batch_size(repository)
        assert batch_size == 500

        dbsession = repository.get_db_session()
        flag = RepositoryFlagFactory(repository=repository, flag_name="flag1")
        dbsession.add(flag)
        dbsession.flush()

        batch_size = backfill_batch_size(repository)
        assert batch_size == 500

        flag = RepositoryFlagFactory(repository=repository, flag_name="flag2")
        dbsession.add(flag)
        dbsession.flush()

        batch_size = backfill_batch_size(repository)
        assert batch_size == 250

        for i in range(8):
            flag = RepositoryFlagFactory(repository=repository, flag_name="flag2")
            dbsession.add(flag)
            dbsession.flush()

        batch_size = backfill_batch_size(repository)
        assert batch_size == 50
