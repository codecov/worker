from datetime import datetime, timezone

import pytest
from shared.reports.readonly import ReadOnlyReport
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.utils.sessions import Session
from shared.yaml import UserYaml

from database.models.timeseries import Dataset, Measurement, MeasurementName
from database.tests.factories import CommitFactory, RepositoryFactory
from database.tests.factories.reports import RepositoryFlagFactory
from database.tests.factories.timeseries import DatasetFactory, MeasurementFactory
from services.timeseries import (
    backfill_batch_size,
    delete_repository_data,
    delete_repository_measurements,
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
def sample_report_for_components():
    report = Report()
    first_file = ReportFile("poker.py")
    first_file.append(1, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(2, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    second_file = ReportFile("folder/poker2.py")
    second_file.append(3, ReportLine.create(coverage=0, sessions=[[0, 0]]))
    second_file.append(4, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    third_file = ReportFile("random.go")
    third_file.append(5, ReportLine.create(coverage=0, sessions=[[0, 0]]))
    third_file.append(6, ReportLine.create(coverage=0, sessions=[[0, 0]]))
    third_file.append(8, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    third_file.append(7, ReportLine.create(coverage=1, sessions=[[0, 0]]))
    report.append(first_file)
    report.append(second_file)
    report.append(third_file)
    report.add_session(
        Session(flags=["test-flag-123", "test-flag-456", "random-flago-987"])
    )
    return report


def _create_repository(dbsession):
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
    component_coverage_dataset = DatasetFactory.create(
        repository_id=repository.repoid,
        name=MeasurementName.component_coverage.value,
        backfilled=False,
    )
    dbsession.add(component_coverage_dataset)
    dbsession.flush()

    return repository


@pytest.fixture
def repository(dbsession):
    return _create_repository(dbsession)


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
        assert measurement.measurable_id == f"{commit.repoid}"
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
            measurable_id=commit.repoid,
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
        assert measurement.measurable_id == f"{commit.repoid}"
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
                measurable_id=f"{repository_flag1.id}",
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.measurable_id == f"{repository_flag1.id}"
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
                measurable_id=f"{repository_flag2.id}",
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.measurable_id == f"{repository_flag2.id}"
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
            measurable_id=repository_flag1.id,
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
            measurable_id=repository_flag2.id,
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
                measurable_id=f"{repository_flag1.id}",
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.measurable_id == f"{repository_flag1.id}"
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
                measurable_id=f"{repository_flag2.id}",
            )
            .one_or_none()
        )

        assert measurement
        assert measurement.name == MeasurementName.flag_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.measurable_id == f"{repository_flag2.id}"
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 100.0

    def test_commit_measurement_insert_components(
        self, dbsession, sample_report_for_components, repository, mocker
    ):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(
                sample_report_for_components
            ),
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        get_repo_yaml = mocker.patch("services.timeseries.get_repo_yaml")
        yaml_dict = {
            "component_management": {
                "default_rules": {
                    "paths": [r".*\.go"],
                    "flag_regexes": [r"test-flag-*"],
                },
                "individual_components": [
                    {"component_id": "python_files", "paths": [r".*\.py"]},
                    {"component_id": "rules_from_default"},
                    {
                        "component_id": "i_have_flags",
                        "flag_regexes": [r"random-.*"],
                    },
                    {
                        "component_id": "all_settings",
                        "name": "all settings",
                        "flag_regexes": [],
                        "paths": [r"folder/*"],
                    },
                    {  # testing duplicate component on purpose this was causing crashes
                        "component_id": "all_settings",
                        "name": "all settings",
                        "flag_regexes": [],
                        "paths": [r"folder/*"],
                    },
                    {
                        "component_id": "path_not_found",
                        "name": "no expected covarage",
                        "flag_regexes": [],
                        "paths": ["asdfasdf"],
                    },
                    {
                        "component_id": "empty_path",
                        "name": "no expected covarage",
                        "flag_regexes": [],
                        "paths": [],
                    },
                ],
            }
        }
        get_repo_yaml.return_value = UserYaml(yaml_dict)
        save_commit_measurements(commit)

        # 1 for coverage, 3 for flags, 4 for valid components
        assert len(dbsession.query(Measurement).all()) == 8

        python_file_measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.component_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                measurable_id="python_files",
            )
            .one_or_none()
        )
        assert python_file_measurement
        assert python_file_measurement.name == MeasurementName.component_coverage.value
        assert python_file_measurement.owner_id == commit.repository.ownerid
        assert python_file_measurement.repo_id == commit.repoid
        assert python_file_measurement.measurable_id == "python_files"
        assert python_file_measurement.commit_sha == commit.commitid
        assert python_file_measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert python_file_measurement.branch == "foo"
        assert python_file_measurement.value == 75.0

        default_component_settings_measurement = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.component_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                measurable_id="rules_from_default",
            )
            .one_or_none()
        )
        assert default_component_settings_measurement
        assert (
            default_component_settings_measurement.name
            == MeasurementName.component_coverage.value
        )
        assert (
            default_component_settings_measurement.owner_id == commit.repository.ownerid
        )
        assert default_component_settings_measurement.repo_id == commit.repoid
        assert (
            default_component_settings_measurement.measurable_id == "rules_from_default"
        )
        assert default_component_settings_measurement.commit_sha == commit.commitid
        assert default_component_settings_measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert default_component_settings_measurement.branch == "foo"
        assert default_component_settings_measurement.value == 25.0

        manual_flags_measurements = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.component_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                measurable_id="i_have_flags",
            )
            .one_or_none()
        )
        assert manual_flags_measurements
        assert (
            manual_flags_measurements.name == MeasurementName.component_coverage.value
        )
        assert manual_flags_measurements.owner_id == commit.repository.ownerid
        assert manual_flags_measurements.repo_id == commit.repoid
        assert manual_flags_measurements.measurable_id == "i_have_flags"
        assert manual_flags_measurements.commit_sha == commit.commitid
        assert manual_flags_measurements.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert manual_flags_measurements.branch == "foo"
        assert manual_flags_measurements.value == 25.0

        all_settings_measurements = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.component_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                measurable_id="all_settings",
            )
            .one_or_none()
        )
        assert all_settings_measurements
        assert (
            all_settings_measurements.name == MeasurementName.component_coverage.value
        )
        assert all_settings_measurements.owner_id == commit.repository.ownerid
        assert all_settings_measurements.repo_id == commit.repoid
        assert all_settings_measurements.measurable_id == "all_settings"
        assert all_settings_measurements.commit_sha == commit.commitid
        assert all_settings_measurements.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert all_settings_measurements.branch == "foo"
        assert all_settings_measurements.value == 50.0

        path_not_found_measurements = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.component_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                measurable_id="path_not_found",
            )
            .one_or_none()
        )
        assert path_not_found_measurements is None

        empty_path_measurements = (
            dbsession.query(Measurement)
            .filter_by(
                name=MeasurementName.component_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                measurable_id="empty_path",
            )
            .one_or_none()
        )
        assert empty_path_measurements is None

    def test_commit_measurement_update_component(
        self, dbsession, sample_report_for_components, repository, mocker
    ):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(
                sample_report_for_components
            ),
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        get_repo_yaml = mocker.patch("services.timeseries.get_repo_yaml")
        yaml_dict = {
            "component_management": {
                "individual_components": [
                    {
                        "component_id": "test-component-123",
                        "name": "test component",
                        "flag_regexes": ["random-flago-987"],
                        "paths": [r"folder/*"],
                    },
                ],
            }
        }
        get_repo_yaml.return_value = UserYaml(yaml_dict)

        measurement = MeasurementFactory.create(
            name=MeasurementName.component_coverage.value,
            owner_id=commit.repository.ownerid,
            repo_id=commit.repoid,
            measurable_id="test-component-123",
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
                name=MeasurementName.component_coverage.value,
                commit_sha=commit.commitid,
                timestamp=commit.timestamp,
                measurable_id="test-component-123",
            )
            .all()
        )

        assert len(measurements) == 1
        measurement = measurements[0]
        assert measurement.name == MeasurementName.component_coverage.value
        assert measurement.owner_id == commit.repository.ownerid
        assert measurement.repo_id == commit.repoid
        assert measurement.commit_sha == commit.commitid
        assert measurement.timestamp.replace(
            tzinfo=timezone.utc
        ) == commit.timestamp.replace(tzinfo=timezone.utc)
        assert measurement.branch == "foo"
        assert measurement.value == 50.0

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
            MeasurementName.component_coverage.value,
        ]

        datasets = repository_datasets_query(repository, backfilled=True)
        assert [dataset.name for dataset in datasets] == [
            MeasurementName.coverage.value,
        ]

        datasets = repository_datasets_query(repository, backfilled=False)
        assert [dataset.name for dataset in datasets] == [
            MeasurementName.flag_coverage.value,
            MeasurementName.component_coverage.value,
        ]

    def test_backfill_batch_size(self, repository, mocker):
        dbsession = repository.get_db_session()
        coverage_dataset = (
            dbsession.query(Dataset.name)
            .filter_by(
                repository_id=repository.repoid, name=MeasurementName.coverage.value
            )
            .first()
        )
        flag_coverage_dataset = (
            dbsession.query(Dataset.name)
            .filter_by(
                repository_id=repository.repoid,
                name=MeasurementName.flag_coverage.value,
            )
            .first()
        )
        component_coverage_dataset = (
            dbsession.query(Dataset.name)
            .filter_by(
                repository_id=repository.repoid,
                name=MeasurementName.component_coverage.value,
            )
            .first()
        )

        # Initially batch size is 500 for all measurement names
        batch_size = backfill_batch_size(repository, coverage_dataset)
        assert batch_size == 500
        batch_size = backfill_batch_size(repository, flag_coverage_dataset)
        assert batch_size == 500
        batch_size = backfill_batch_size(repository, component_coverage_dataset)
        assert batch_size == 500

        dbsession = repository.get_db_session()
        flag1 = RepositoryFlagFactory(repository=repository, flag_name="flag1")
        flag2 = RepositoryFlagFactory(repository=repository, flag_name="flag2")
        dbsession.add(flag1)
        dbsession.add(flag2)
        dbsession.flush()

        # Adding flags should only affect flag coverage measurement
        batch_size = backfill_batch_size(repository, coverage_dataset)
        assert batch_size == 500
        batch_size = backfill_batch_size(repository, flag_coverage_dataset)
        assert batch_size == 250
        batch_size = backfill_batch_size(repository, component_coverage_dataset)
        assert batch_size == 500

        get_repo_yaml = mocker.patch("services.timeseries.get_repo_yaml")
        yaml_dict = {
            "component_management": {
                "default_rules": {
                    "paths": [r".*\.go"],
                    "flag_regexes": [r"test-flag-*"],
                },
                "individual_components": [
                    {"component_id": "component_1"},
                    {"component_id": "component_2"},
                    {"component_id": "component_3"},
                    {"component_id": "component_4"},
                    {"component_id": "component_5"},
                ],
            }
        }
        get_repo_yaml.return_value = UserYaml(yaml_dict)

        # Adding componets should only affect component coverage measurement
        batch_size = backfill_batch_size(repository, coverage_dataset)
        assert batch_size == 500
        batch_size = backfill_batch_size(repository, flag_coverage_dataset)
        assert batch_size == 250
        batch_size = backfill_batch_size(repository, component_coverage_dataset)
        assert batch_size == 100

    def test_delete_repository_data(self, dbsession, sample_report, repository, mocker):
        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
        )

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()
        save_commit_measurements(commit)
        commit = CommitFactory.create(branch="bar", repository=repository)
        dbsession.add(commit)
        dbsession.flush()
        save_commit_measurements(commit)

        assert (
            dbsession.query(Dataset).filter_by(repository_id=repository.repoid).count()
            == 3
        )
        # repo coverage + 2x flag coverage for each commit
        assert (
            dbsession.query(Measurement).filter_by(repo_id=repository.repoid).count()
            == 6
        )

        delete_repository_data(repository)

        assert (
            dbsession.query(Dataset).filter_by(repository_id=repository.repoid).count()
            == 0
        )
        assert (
            dbsession.query(Measurement).filter_by(repo_id=repository.repoid).count()
            == 0
        )

    def test_delete_repository_data_side_effects(
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
        commit = CommitFactory.create(branch="bar", repository=repository)
        dbsession.add(commit)
        dbsession.flush()
        save_commit_measurements(commit)

        # Another unrelated repository, make sure that this one isn't deleted as a side effect
        other_repository = _create_repository(dbsession)
        other_commit = CommitFactory.create(branch="foo", repository=other_repository)
        dbsession.add(other_commit)
        dbsession.flush()
        save_commit_measurements(other_commit)
        other_commit = CommitFactory.create(branch="bar", repository=other_repository)
        dbsession.add(other_commit)
        dbsession.flush()
        save_commit_measurements(other_commit)

        delete_repository_data(repository)

        # Intended repo data/measurement is deleted
        assert (
            dbsession.query(Dataset).filter_by(repository_id=repository.repoid).count()
            == 0
        )
        assert (
            dbsession.query(Measurement).filter_by(repo_id=repository.repoid).count()
            == 0
        )

        # Other repo data/measurement is not deleted
        assert (
            dbsession.query(Dataset)
            .filter_by(repository_id=other_repository.repoid)
            .count()
            != 0
        )
        assert (
            dbsession.query(Measurement)
            .filter_by(repo_id=other_repository.repoid)
            .count()
            != 0
        )

    def test_delete_repository_data_measurements_only(
        self, dbsession, sample_report_for_components, repository, mocker
    ):
        def validate_invariants(repository, other_repository):
            assert (
                dbsession.query(Dataset)
                .filter_by(repository_id=repository.repoid)
                .count()
                == 3
            )
            assert (
                dbsession.query(Dataset)
                .filter_by(repository_id=other_repository.repoid)
                .count()
                == 3
            )
            # 2x(1 coverage, 3 flag coverage, 4 component coverage)
            assert (
                dbsession.query(Measurement)
                .filter_by(repo_id=other_repository.repoid)
                .count()
                == 16
            )

        mocker.patch("services.timeseries.timeseries_enabled", return_value=True)
        mocker.patch(
            "services.report.ReportService.get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(
                sample_report_for_components
            ),
        )

        get_repo_yaml = mocker.patch("services.timeseries.get_repo_yaml")
        yaml_dict = {
            "component_management": {
                "default_rules": {
                    "paths": [r".*\.go"],
                    "flag_regexes": [r"test-flag-*"],
                },
                "individual_components": [
                    {"component_id": "python_files", "paths": [r".*\.py"]},
                    {"component_id": "rules_from_default"},
                    {
                        "component_id": "i_have_flags",
                        "flag_regexes": [r"random-.*"],
                    },
                    {
                        "component_id": "all_settings",
                        "name": "all settings",
                        "flag_regexes": [],
                        "paths": [r"folder/*"],
                    },
                ],
            }
        }
        get_repo_yaml.return_value = UserYaml(yaml_dict)

        commit = CommitFactory.create(branch="foo", repository=repository)
        dbsession.add(commit)
        dbsession.flush()
        save_commit_measurements(commit)
        commit = CommitFactory.create(branch="bar", repository=repository)
        dbsession.add(commit)
        dbsession.flush()
        save_commit_measurements(commit)

        # Another unrelated repository, make sure that this one isn't deleted as a side effect
        other_repository = _create_repository(dbsession)
        other_commit = CommitFactory.create(branch="foo", repository=other_repository)
        dbsession.add(other_commit)
        dbsession.flush()
        save_commit_measurements(other_commit)
        other_commit = CommitFactory.create(branch="bar", repository=other_repository)
        dbsession.add(other_commit)
        dbsession.flush()
        save_commit_measurements(other_commit)

        flag_ids = set(
            [
                flag.measurable_id
                for flag in (
                    dbsession.query(Measurement).filter_by(
                        repo_id=repository.repoid,
                        name=MeasurementName.flag_coverage.value,
                    )
                )
            ]
        )

        # 2x(1 coverage, 3 flag coverage, 4 component coverage) = 16
        assert (
            dbsession.query(Measurement).filter_by(repo_id=repository.repoid).count()
            == 16
        )
        validate_invariants(repository, other_repository)

        # Delete the coverage type
        delete_repository_measurements(
            repository, MeasurementName.coverage.value, f"{repository.repoid}"
        )

        # 2x(0 coverage, 3 flag coverage, 4 component coverage) = 14
        assert (
            dbsession.query(Measurement).filter_by(repo_id=repository.repoid).count()
            == 14
        )
        validate_invariants(repository, other_repository)

        # Delete the flag coverages
        expected_measurement_count = 14
        for flag_id in flag_ids:
            assert (
                dbsession.query(Measurement)
                .filter_by(repo_id=repository.repoid)
                .count()
                == expected_measurement_count
            )
            validate_invariants(repository, other_repository)
            delete_repository_measurements(
                repository, MeasurementName.flag_coverage.value, f"{flag_id}"
            )
            # Lose a flag coverage measurement from each commit (ie total should be 2 less)
            expected_measurement_count -= 2

        # 2x(0 coverage, 0 flag coverage, 4 component coverage) = 8
        assert (
            dbsession.query(Measurement).filter_by(repo_id=repository.repoid).count()
            == expected_measurement_count
        )
        validate_invariants(repository, other_repository)

        for component in yaml_dict["component_management"]["individual_components"]:
            assert (
                dbsession.query(Measurement)
                .filter_by(repo_id=repository.repoid)
                .count()
                == expected_measurement_count
            )
            validate_invariants(repository, other_repository)
            component_id = component["component_id"]
            delete_repository_measurements(
                repository, MeasurementName.component_coverage.value, component_id
            )
            # Lose a component coverage measurement from each commit (ie total should be 2 less)
            expected_measurement_count -= 2

        # 2x(0 coverage, 0 flag coverage, 0 component coverage) = 0
        assert (
            dbsession.query(Measurement).filter_by(repo_id=repository.repoid).count()
            == expected_measurement_count
        )
        validate_invariants(repository, other_repository)
