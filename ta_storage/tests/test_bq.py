from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import test_results_parser

import generated_proto.testrun.ta_testrun_pb2 as ta_testrun_pb2
from database.tests.factories import RepositoryFlagFactory, UploadFactory
from ta_storage.bq import DATASET_NAME, TESTRUN_TABLE_NAME, BQDriver


@pytest.fixture
def mock_bigquery_service():
    with patch("ta_storage.bq.get_bigquery_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


def test_bigquery_driver(dbsession, mock_bigquery_service):
    bq = BQDriver()

    upload = UploadFactory()
    dbsession.add(upload)
    dbsession.flush()

    repo_flag_1 = RepositoryFlagFactory(
        repository=upload.report.commit.repository, flag_name="flag1"
    )
    repo_flag_2 = RepositoryFlagFactory(
        repository=upload.report.commit.repository, flag_name="flag2"
    )
    dbsession.add(repo_flag_1)
    dbsession.add(repo_flag_2)
    dbsession.flush()

    upload.flags.append(repo_flag_1)
    upload.flags.append(repo_flag_2)
    dbsession.flush()

    test_data: list[test_results_parser.Testrun] = [
        {
            "name": "test_name",
            "classname": "test_class",
            "testsuite": "test_suite",
            "duration": 100.0,
            "outcome": "pass",
            "build_url": "https://example.com/build/123",
            "filename": "test_file",
            "computed_name": "test_computed_name",
            "failure_message": None,
        },
        {
            "name": "test_name2",
            "classname": "test_class2",
            "testsuite": "test_suite2",
            "duration": 100.0,
            "outcome": "failure",
            "build_url": "https://example.com/build/123",
            "filename": "test_file2",
            "computed_name": "test_computed_name2",
            "failure_message": "test_failure_message",
        },
    ]

    timestamp = int(datetime.now().timestamp() * 1000000)

    bq.write_testruns(
        timestamp,
        upload.report.commit.repoid,
        upload.report.commit.commitid,
        upload.report.commit.branch,
        upload,
        "pytest",
        test_data,
    )

    # Verify the BigQuery service was called correctly
    mock_bigquery_service.write.assert_called_once_with(
        DATASET_NAME,
        TESTRUN_TABLE_NAME,
        ta_testrun_pb2,
        [
            ta_testrun_pb2.TestRun(
                timestamp=timestamp,
                name="test_name",
                classname="test_class",
                testsuite="test_suite",
                duration_seconds=100.0,
                outcome=ta_testrun_pb2.TestRun.Outcome.PASSED,
                filename="test_file",
                computed_name="test_computed_name",
                failure_message=None,
                repoid=upload.report.commit.repoid,
                commit_sha=upload.report.commit.commitid,
                framework="pytest",
                branch_name=upload.report.commit.branch,
                flags=["flag1", "flag2"],
            ).SerializeToString(),
            ta_testrun_pb2.TestRun(
                timestamp=timestamp,
                name="test_name2",
                classname="test_class2",
                testsuite="test_suite2",
                duration_seconds=100.0,
                outcome=ta_testrun_pb2.TestRun.Outcome.FAILED,
                filename="test_file2",
                computed_name="test_computed_name2",
                failure_message="test_failure_message",
                repoid=upload.report.commit.repoid,
                commit_sha=upload.report.commit.commitid,
                framework="pytest",
                branch_name=upload.report.commit.branch,
                flags=["flag1", "flag2"],
            ).SerializeToString(),
        ],
    )
