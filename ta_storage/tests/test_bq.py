from datetime import datetime, timezone
from unittest.mock import ANY, MagicMock, patch

import polars as pl
import pytest
import test_results_parser
from google.cloud.bigquery import (
    ArrayQueryParameter,
    ScalarQueryParameter,
    StructQueryParameterType,
)
from google.protobuf.json_format import MessageToDict
from shared.django_apps.reports.tests.factories import (
    UploadFactory,
)
from shared.django_apps.test_analytics.models import Flake
from time_machine import travel

import generated_proto.testrun.ta_testrun_pb2 as ta_testrun_pb2
from ta_storage.bq import BQDriver
from ta_storage.utils import calc_flags_hash, calc_test_id


@pytest.fixture()
def mock_bigquery_service():
    with patch("ta_storage.bq.get_bigquery_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture()
def mock_config(mock_configuration):
    mock_configuration._params["services"]["gcp"] = {
        "project_id": "test-project",
    }
    mock_configuration._params["services"]["bigquery"] = {
        "dataset_name": "test-dataset",
        "testrun_table_name": "test-table",
    }


def read_table(mock_storage, bucket: str, storage_path: str):
    decompressed_table: bytes = mock_storage.read_file(bucket, storage_path)
    return pl.read_ipc(decompressed_table)


@pytest.mark.django_db(transaction=True, databases=["test_analytics"])
def test_write_testruns(mock_bigquery_service, mock_config, snapshot):
    driver = BQDriver(repo_id=1)
    timestamp = int(
        datetime.fromisoformat("2025-01-01T00:00:00Z").timestamp() * 1000000
    )

    testruns: list[test_results_parser.Testrun] = [
        {
            "name": "test_something",
            "classname": "TestClass",
            "testsuite": "test_suite",
            "computed_name": "TestClass.test_something",
            "outcome": "pass",
            "failure_message": None,
            "duration": 1.5,
            "filename": "test_file.py",
            "build_url": None,
        }
    ]

    driver.write_testruns(
        timestamp=timestamp,
        commit_sha="abc123",
        branch_name="main",
        upload_id=1,
        flag_names=["unit"],
        framework="pytest",
        testruns=testruns,
    )

    mock_bigquery_service.write.assert_called_once_with(
        "test-dataset", "test-table", ta_testrun_pb2, ANY
    )

    testruns_written = [
        MessageToDict(
            ta_testrun_pb2.TestRun.FromString(testrun_bytes),
            preserving_proto_field_name=True,
        )
        for testrun_bytes in mock_bigquery_service.mock_calls[0][1][3]
    ]
    assert snapshot("json") == sorted(testruns_written, key=lambda x: x["name"])


@pytest.mark.django_db(transaction=True, databases=["test_analytics"])
def test_write_testruns_with_flake(mock_bigquery_service, mock_config, snapshot):
    driver = BQDriver(repo_id=1)
    timestamp = int(
        datetime.fromisoformat("2025-01-01T00:00:00Z").timestamp() * 1000000
    )

    flake = Flake.objects.create(
        repoid=1,
        test_id=calc_test_id("test_suite", "TestClass", "test_something"),
        flags_id=calc_flags_hash(["unit"]),
        fail_count=1,
        count=1,
        recent_passes_count=1,
        start_date=datetime.now(timezone.utc),
    )
    flake.save()

    testruns: list[test_results_parser.Testrun] = [
        {
            "name": "test_something",
            "classname": "TestClass",
            "testsuite": "test_suite",
            "computed_name": "TestClass.test_something",
            "outcome": "failure",
            "failure_message": "assertion failed",
            "duration": 1.5,
            "filename": "test_file.py",
            "build_url": None,
        }
    ]

    driver.write_testruns(
        timestamp=timestamp,
        commit_sha="abc123",
        branch_name="main",
        upload_id=1,
        flag_names=["unit"],
        framework="pytest",
        testruns=testruns,
    )

    mock_bigquery_service.write.assert_called_once_with(
        "test-dataset", "test-table", ta_testrun_pb2, ANY
    )

    testruns_written = [
        MessageToDict(
            ta_testrun_pb2.TestRun.FromString(testrun_bytes),
            preserving_proto_field_name=True,
        )
        for testrun_bytes in mock_bigquery_service.mock_calls[0][1][3]
    ]
    assert snapshot("json") == sorted(testruns_written, key=lambda x: x["name"])


def test_pr_comment_agg(mock_bigquery_service, mock_config, snapshot):
    driver = BQDriver(repo_id=1)
    mock_bigquery_service.query.return_value = [
        {
            "commit_sha": "abc123",
            "passed": 10,
            "failed": 2,
            "skipped": 1,
            "flaky_failed": 1,
        }
    ]

    result = driver.pr_comment_agg("abc123")

    mock_bigquery_service.query.assert_called_once()
    query, params = mock_bigquery_service.query.call_args[0]
    assert snapshot("txt") == query
    assert params == [
        ScalarQueryParameter("repoid", "INT64", 1),
        ScalarQueryParameter("commit_sha", "STRING", "abc123"),
    ]
    assert snapshot("json") == result


def test_pr_comment_fail(mock_bigquery_service, mock_config, snapshot):
    driver = BQDriver(repo_id=1)
    mock_bigquery_service.query.return_value = [
        {
            "computed_name": "TestClass.test_something",
            "failure_message": "assertion failed",
            "test_id": b"test_id",
            "flags_hash": b"flags_hash",
            "duration_seconds": 1.5,
            "upload_id": 1,
        }
    ]

    result = driver.pr_comment_fail("abc123")

    # Verify the query parameters
    mock_bigquery_service.query.assert_called_once()
    query, params = mock_bigquery_service.query.call_args[0]
    assert snapshot("txt") == query
    assert params == [
        ScalarQueryParameter("repoid", "INT64", 1),
        ScalarQueryParameter("commit_sha", "STRING", "abc123"),
    ]
    result[0]["id"] = [result[0]["id"][0].hex(), result[0]["id"][1].hex()]
    assert snapshot("json") == result


@travel("2025-01-01T00:00:00Z", tick=False)
@pytest.mark.django_db(transaction=True, databases=["default", "test_analytics"])
def test_write_flakes(mock_bigquery_service, mock_config, snapshot):
    driver = BQDriver(repo_id=1)

    upload = UploadFactory.create()
    upload.save()

    mock_bigquery_service.query.return_value = [
        {
            "branch_name": "main",
            "timestamp": int(datetime.now().timestamp() * 1000000),
            "outcome": ta_testrun_pb2.TestRun.Outcome.FAILED,
            "test_id": b"test_id",
            "flags_hash": b"flags_hash",
        }
    ]

    driver.write_flakes([upload])

    mock_bigquery_service.query.assert_called_once()
    query, params = mock_bigquery_service.query.call_args[0]
    assert snapshot("txt") == query
    assert params == [
        ScalarQueryParameter("upload_id", "INT64", upload.id),
        ArrayQueryParameter(
            "flake_ids",
            StructQueryParameterType(
                ScalarQueryParameter("test_id", "STRING", "test_id"),
                ScalarQueryParameter("flags_id", "STRING", "flags_id"),
            ),
            [],
        ),
    ]

    flakes = Flake.objects.all()
    flake_data = [
        {
            "repoid": flake.repoid,
            "test_id": flake.test_id.hex(),
            "fail_count": flake.fail_count,
            "count": flake.count,
            "recent_passes_count": flake.recent_passes_count,
            "start_date": flake.start_date.isoformat() if flake.start_date else None,
            "end_date": flake.end_date.isoformat() if flake.end_date else None,
            "flags_id": flake.flags_id.hex() if flake.flags_id else None,
        }
        for flake in flakes
    ]
    assert snapshot("json") == sorted(flake_data, key=lambda x: x["test_id"])


def test_analytics(mock_bigquery_service, mock_config, snapshot):
    driver = BQDriver(repo_id=1)

    _ = driver.analytics(1, 30, 0)
    query, params = mock_bigquery_service.query.call_args[0]
    assert snapshot("txt") == query
    assert params == [
        ScalarQueryParameter("repoid", "INT64", 1),
        ScalarQueryParameter("interval_start", "INT64", 30),
        ScalarQueryParameter("interval_end", "INT64", 0),
    ]


def test_analytics_with_branch(mock_bigquery_service, mock_config, snapshot):
    driver = BQDriver(repo_id=1)

    _ = driver.analytics(1, 30, 0, "main")
    query, params = mock_bigquery_service.query.call_args[0]
    assert snapshot("txt") == query
    assert params == [
        ScalarQueryParameter("repoid", "INT64", 1),
        ScalarQueryParameter("interval_start", "INT64", 30),
        ScalarQueryParameter("interval_end", "INT64", 0),
        ScalarQueryParameter("branch", "STRING", "main"),
    ]


@travel("2025-01-01T00:00:00Z", tick=False)
def test_cache_analytics(mock_bigquery_service, mock_config, mock_storage, snapshot):
    driver = BQDriver(repo_id=1)

    # Mock the analytics query result with datetime
    mock_bigquery_service.query.return_value = [
        {
            "name": "test_something",
            "classname": "TestClass",
            "testsuite": "test_suite",
            "computed_name": "TestClass.test_something",
            "flags": ["unit"],
            "avg_duration": 1.5,
            "fail_count": 2,
            "flaky_fail_count": 1,
            "pass_count": 10,
            "skip_count": 1,
            "commits_where_fail": 2,
            "last_duration": 1.2,
            "updated_at": datetime.fromisoformat("2025-01-01T00:00:00+00:00"),
        }
    ]

    buckets = ["bucket1", "bucket2"]
    branch = "main"
    driver.cache_analytics(buckets, branch)

    assert mock_bigquery_service.query.call_count == 6

    expected_intervals = [
        (1, None),
        (2, 1),
        (7, None),
        (14, 7),
        (30, None),
        (60, 30),
    ]

    expected_dict = {
        "name": [],
        "classname": [],
        "testsuite": [],
        "computed_name": [],
        "flags": [],
        "avg_duration": [],
        "fail_count": [],
        "flaky_fail_count": [],
        "pass_count": [],
        "skip_count": [],
        "commits_where_fail": [],
        "last_duration": [],
    }

    table_dicts = []
    for bucket in buckets:
        for interval_start, interval_end in expected_intervals:
            storage_key = (
                f"ta_rollups/{driver.repo_id}/{branch}/{interval_start}"
                if interval_end is None
                else f"ta_rollups/{driver.repo_id}/{branch}/{interval_start}_{interval_end}"
            )
            table = read_table(mock_storage, bucket, storage_key)
            table_dict = table.to_dict(as_series=False)
            table_dicts.append(table_dict)

    assert snapshot("json") == {
        "name": table_dicts[0]["name"],
        "classname": table_dicts[0]["classname"],
        "testsuite": table_dicts[0]["testsuite"],
        "computed_name": table_dicts[0]["computed_name"],
        "flags": table_dicts[0]["flags"],
        "avg_duration": table_dicts[0]["avg_duration"],
        "fail_count": table_dicts[0]["fail_count"],
        "flaky_fail_count": table_dicts[0]["flaky_fail_count"],
        "pass_count": table_dicts[0]["pass_count"],
        "skip_count": table_dicts[0]["skip_count"],
        "commits_where_fail": table_dicts[0]["commits_where_fail"],
        "last_duration": table_dicts[0]["last_duration"],
    }

    first_dict = table_dicts[0]
    for table_dict in table_dicts[1:]:
        assert table_dict == first_dict

    queries = []
    params = []
    for args in mock_bigquery_service.query.call_args_list:
        queries.append(args[0][0])
        params.append(args[0][1])

    first_query = queries[0]
    for query in queries[1:]:
        assert query == first_query

    assert snapshot("txt") == first_query

    for i, (interval_start, interval_end) in enumerate(expected_intervals):
        assert params[i] == [
            ScalarQueryParameter("repoid", "INT64", 1),
            ScalarQueryParameter("interval_start", "INT64", interval_start),
            ScalarQueryParameter("interval_end", "INT64", interval_end),
            ScalarQueryParameter("branch", "STRING", branch),
        ]
