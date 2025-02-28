from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import test_results_parser
from shared.config import ConfigHelper
from shared.django_apps.core.tests.factories import CommitFactory, RepositoryFactory
from shared.django_apps.reports.models import UploadError
from shared.django_apps.reports.tests.factories import (
    RepositoryFlagFactory,
    UploadFactory,
    UploadFlagMembershipFactory,
)
from shared.django_apps.test_analytics.models import Flake
from shared.django_apps.timeseries.models import Testrun
from shared.storage.exceptions import FileNotInStorageError
from shared.yaml import UserYaml

from services.test_analytics.ta_processing import (
    TAProcInfo,
    delete_archive,
    get_ta_processing_info,
    handle_file_not_found,
    handle_parsing_error,
    insert_testruns_timeseries,
    should_delete_archive,
)
from services.test_analytics.ta_timeseries import calc_test_id


@pytest.mark.django_db(databases=["default", "timeseries"])
def test_get_ta_processing_info():
    repository = RepositoryFactory.create()
    commit = CommitFactory.create(repository=repository, branch="main")

    result = get_ta_processing_info(repository.repoid, commit.commitid, {})

    assert isinstance(result, TAProcInfo)
    assert result.repository == repository
    assert result.branch == "main"
    assert isinstance(result.user_yaml, UserYaml)


@pytest.mark.django_db(databases=["default", "timeseries"])
def test_get_ta_processing_info_no_branch():
    repository = RepositoryFactory.create()
    commit = CommitFactory.create(repository=repository, branch=None)

    commit_yaml = {"codecov": {"notify": {"after_n_builds": 1}}}

    with pytest.raises(ValueError, match="Branch is None"):
        get_ta_processing_info(repository.repoid, commit.commitid, commit_yaml)


def test_should_delete_archive_config_enabled():
    mock_config = ConfigHelper()
    mock_config.set_params({"services": {"minio": {"expire_raw_after_n_days": 7}}})

    with patch("services.test_analytics.ta_processing.get_config", return_value=7):
        assert should_delete_archive(UserYaml({})) is True


def test_should_delete_archive_yaml_disabled():
    mock_config = ConfigHelper()
    mock_config.set_params({"services": {"minio": {}}})

    with patch("services.test_analytics.ta_processing.get_config", return_value=None):
        user_yaml = UserYaml({"codecov": {"archive": {"uploads": False}}})
        assert should_delete_archive(user_yaml) is True


def test_should_delete_archive_yaml_enabled():
    mock_config = ConfigHelper()
    mock_config.set_params({"services": {"minio": {}}})

    with patch("services.test_analytics.ta_processing.get_config", return_value=None):
        user_yaml = UserYaml({"codecov": {"archive": {"uploads": True}}})
        assert should_delete_archive(user_yaml) is False


@pytest.mark.django_db(databases=["default", "timeseries"])
def test_delete_archive(storage):
    repository = RepositoryFactory.create()
    commit = CommitFactory.create(repository=repository)
    upload = UploadFactory.create(
        report__commit=commit, storage_path="path/to/archive.xml"
    )

    storage.write_file("archive", "path/to/archive.xml", b"test content")

    delete_archive(storage, upload, "archive")

    with pytest.raises(FileNotInStorageError):
        storage.read_file("archive", "path/to/archive.xml")


@pytest.mark.django_db(databases=["default", "timeseries"])
def test_delete_archive_http_path(storage):
    repository = RepositoryFactory.create()
    commit = CommitFactory.create(repository=repository)
    upload = UploadFactory.create(
        report__commit=commit, storage_path="http://example.com/archive.xml"
    )

    storage.write_file("archive", "path/to/archive.xml", b"test content")

    delete_archive(storage, upload, "archive")

    assert storage.read_file("archive", "path/to/archive.xml") == b"test content"


@pytest.mark.django_db(databases=["default", "timeseries"])
def test_handle_file_not_found():
    repository = RepositoryFactory.create()
    commit = CommitFactory.create(repository=repository)
    upload = UploadFactory.create(report__commit=commit, state="started")

    handle_file_not_found(upload)

    upload.refresh_from_db()
    assert upload.state == "processed"

    error = UploadError.objects.get(report_session=upload)
    assert error.error_code == "file_not_in_storage"
    assert error.error_params == {}


@pytest.mark.django_db(databases=["default", "timeseries"])
def test_handle_parsing_error():
    repository = RepositoryFactory.create()
    commit = CommitFactory.create(repository=repository)
    upload = UploadFactory.create(report__commit=commit, state="started")

    test_exception = ValueError("Test error")
    mock_capture_exception = MagicMock()

    with patch("sentry_sdk.capture_exception", mock_capture_exception):
        handle_parsing_error(upload, test_exception)

    upload.refresh_from_db()
    assert upload.state == "processed"

    error = UploadError.objects.get(report_session=upload)
    assert error.error_code == "unsupported_file_format"
    assert error.error_params == {"error_message": "Test error"}

    mock_capture_exception.assert_called_once_with(
        test_exception, tags={"upload_state": "started"}
    )


@pytest.mark.django_db(databases=["default", "timeseries"])
def test_insert_testruns_timeseries():
    repository = RepositoryFactory.create()
    commit = CommitFactory.create(repository=repository)
    flag = RepositoryFlagFactory.create(repository=repository, flag_name="unit")
    upload = UploadFactory.create(report__commit=commit)
    UploadFlagMembershipFactory.create(report_session=upload, flag=flag, id=upload.id)

    test_id = calc_test_id("test_name", "test_classname", "test_suite")
    flaky_test_ids = {test_id}

    Flake.objects.create(
        repoid=repository.repoid,
        test_id=test_id,
        end_date=None,
        start_date=datetime.now(),
        count=0,
        fail_count=0,
        recent_passes_count=0,
        flags_id=None,
    )

    testrun: test_results_parser.Testrun = {
        "name": "test_name",
        "classname": "test_classname",
        "testsuite": "test_suite",
        "computed_name": "computed_name",
        "duration": 1.0,
        "outcome": "pass",
        "failure_message": None,
        "filename": "test_filename",
        "build_url": None,
    }

    parsing_info: test_results_parser.ParsingInfo = {
        "framework": "Pytest",
        "testruns": [testrun],
    }

    parsing_infos = [parsing_info]

    insert_testruns_timeseries(
        repository.repoid, commit.commitid, commit.branch, upload, parsing_infos
    )

    testrun_db = Testrun.objects.get(
        name="test_name",
        classname="test_classname",
        testsuite="test_suite",
    )
    assert testrun_db.branch == commit.branch
    assert testrun_db.upload_id == upload.id
    assert testrun_db.flags == upload.flag_names
    assert testrun_db.duration_seconds == 1.0
    assert testrun_db.outcome == "pass"
    assert bytes(testrun_db.test_id) in flaky_test_ids
