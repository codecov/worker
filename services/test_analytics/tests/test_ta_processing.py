from __future__ import annotations

from datetime import datetime

import pytest
import test_results_parser
from shared.django_apps.reports.models import UploadError
from shared.django_apps.reports.tests.factories import UploadFactory
from shared.django_apps.ta_timeseries.models import Testrun
from shared.storage import get_appropriate_storage_service
from shared.storage.exceptions import BucketAlreadyExistsError, FileNotInStorageError

from services.archive import ArchiveService
from services.test_analytics.ta_processing import (
    handle_file_not_found,
    handle_parsing_error,
    insert_testruns_timeseries,
    rewrite_or_delete_upload,
    should_delete_archive_settings,
)
from services.yaml import UserYaml


@pytest.fixture(autouse=True)
def minio_service(custom_config):
    conf = {
        "services": {
            "minio": {
                "port": 9000,
            },
        }
    }

    custom_config(conf)

    storage = get_appropriate_storage_service(1)
    try:
        storage.create_root_storage()
    except BucketAlreadyExistsError:
        pass


@pytest.mark.django_db
def test_handle_file_not_found():
    upload = UploadFactory()

    handle_file_not_found(upload)

    assert upload.state == "processed"

    error = UploadError.objects.filter(report_session=upload).first()
    assert error is not None
    assert error.error_code == "file_not_in_storage"


@pytest.mark.django_db
def test_parsing_error():
    upload = UploadFactory()

    handle_parsing_error(upload, Exception("test string"))

    assert upload.state == "processed"

    error = UploadError.objects.filter(report_session=upload).first()
    assert error is not None
    assert error.error_code == "unsupported_file_format"
    assert error.error_params["error_message"] == "test string"


@pytest.mark.parametrize(
    "expire_raw,uploads,result",
    [
        (None, None, False),
        (7, None, True),
        (True, None, True),
        (None, False, True),
    ],
)
def test_should_delete_archive(expire_raw, uploads, result, custom_config):
    custom_config(
        {
            "services": {
                "minio": {"expire_raw_after_n_days": expire_raw},
            }
        }
    )

    fake_yaml = UserYaml.from_dict(
        {"codecov": {"archive": {"uploads": uploads}}} if uploads is not None else {}
    )
    assert should_delete_archive_settings(fake_yaml) == result


@pytest.mark.django_db
def test_rewrite_or_delete_upload_deletes(custom_config):
    conf = {
        "services": {
            "minio": {
                "port": 9000,
                "expire_raw_after_n_days": 1,
            },
        }
    }

    custom_config(conf)

    upload = UploadFactory(storage_path="url")
    archive_service = ArchiveService(upload.report.commit.repository)

    archive_service.write_file(upload.storage_path, b"test")

    rewrite_or_delete_upload(
        archive_service, UserYaml.from_dict({}), upload, b"rewritten"
    )

    with pytest.raises(FileNotInStorageError):
        archive_service.read_file(upload.storage_path)


@pytest.mark.django_db
def test_rewrite_or_delete_upload_does_not_delete(custom_config):
    conf = {
        "services": {
            "minio": {
                "port": 9000,
                "expire_raw_after_n_days": 1,
            },
        }
    }

    custom_config(conf)

    upload = UploadFactory(storage_path="http_url")
    archive_service = ArchiveService(upload.report.commit.repository)

    archive_service.write_file(upload.storage_path, b"test")

    rewrite_or_delete_upload(
        archive_service, UserYaml.from_dict({}), upload, b"rewritten"
    )

    assert archive_service.read_file(upload.storage_path) == b"test"


@pytest.mark.django_db
def test_rewrite_or_delete_upload_rewrites(custom_config):
    conf = {
        "services": {
            "minio": {
                "port": 9000,
            },
        }
    }

    custom_config(conf)

    upload = UploadFactory(storage_path="url")
    archive_service = ArchiveService(upload.report.commit.repository)

    archive_service.write_file(upload.storage_path, b"test")

    rewrite_or_delete_upload(
        archive_service, UserYaml.from_dict({}), upload, b"rewritten"
    )

    assert archive_service.read_file(upload.storage_path) == b"rewritten"


@pytest.mark.django_db(databases=["default", "ta_timeseries"])
def test_insert_testruns_timeseries(snapshot):
    parsing_infos: list[test_results_parser.ParsingInfo] = [
        {
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_1_name",
                    "classname": "test_1_classname",
                    "duration": 1,
                    "outcome": "pass",
                    "testsuite": "test_1_testsuite",
                    "failure_message": None,
                    "filename": "test_1_file",
                    "build_url": "test_1_build_url",
                    "computed_name": "test_1_computed_name",
                }
            ],
        },
        {
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_2_name",
                    "classname": "test_2_classname",
                    "duration": 1,
                    "outcome": "failure",
                    "testsuite": "test_2_testsuite",
                    "failure_message": "test_2_failure_message",
                    "filename": "test_2_file",
                    "build_url": "test_2_build_url",
                    "computed_name": "test_2",
                }
            ],
        },
    ]

    upload = UploadFactory()
    upload.report.commit.repository.repoid = 1
    upload.report.commit.commitid = "123"
    upload.report.commit.branch = "main"
    upload.id = 1
    upload.created_at = datetime(2025, 1, 1, 0, 0, 0)

    insert_testruns_timeseries(
        repoid=upload.report.commit.repository.repoid,
        commitid=upload.report.commit.commitid,
        branch=upload.report.commit.branch,
        upload=upload,
        parsing_infos=parsing_infos,
    )

    testruns = Testrun.objects.filter(upload_id=upload.id)
    assert testruns.count() == 2

    testruns_list = list(
        testruns.values(
            "timestamp",
            "test_id",
            "name",
            "classname",
            "testsuite",
            "computed_name",
            "outcome",
            "duration_seconds",
            "failure_message",
            "framework",
            "filename",
            "repo_id",
            "commit_sha",
            "branch",
            "flags",
            "upload_id",
        )
    )

    for testrun in testruns_list:
        testrun["timestamp"] = testrun["timestamp"].isoformat()
        testrun["test_id"] = testrun["test_id"].hex()

    assert snapshot("json") == testruns_list
