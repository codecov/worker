from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import test_results_parser
import time_machine

import generated_proto.testrun.ta_testrun_pb2 as ta_testrun_pb2
from database.tests.factories import RepositoryFlagFactory, UploadFactory
from ta_storage.bq import BQDriver
from ta_storage.utils import calc_flags_hash, calc_test_id


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

    flags_hash = calc_flags_hash(upload.flag_names)

    # Verify the BigQuery service was called correctly
    mock_bigquery_service.write.assert_called_once_with(
        bq.dataset_name,
        bq.testrun_table_name,
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
                upload_id=upload.id_,
                flags_hash=flags_hash,
                test_id=calc_test_id("test_name", "test_class", "test_suite"),
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
                upload_id=upload.id_,
                flags_hash=flags_hash,
                test_id=calc_test_id("test_name2", "test_class2", "test_suite2"),
            ).SerializeToString(),
        ],
    )


def populate_pr_comment_testruns(bq: BQDriver):
    testruns = []

    for i in range(3):
        upload = UploadFactory()
        upload.report.commit.commitid = "abcde"
        upload.report.commit.branch = "feature_branch"
        upload.report.commit.repoid = 2
        upload.flags.append(RepositoryFlagFactory(flag_name=f"flag_{i}"))

        for j in range(3):
            name = f"test_{j}"
            classname = f"class_{j}"
            testsuite = "suite_feature"

            testrun: test_results_parser.Testrun = {
                "name": name,
                "classname": classname,
                "testsuite": testsuite,
                "duration": float(j % 5),
                "outcome": "pass" if j % 2 == 0 else "failure",
                "filename": None,
                "computed_name": f"pr_computed_name_{j}",
                "failure_message": None if j % 2 == 0 else "hi",
                "build_url": None,
            }

            testruns.append(testrun)

        bq.write_testruns(
            None, 2, "abcde", "feature_branch", upload, "pytest", testruns
        )


@pytest.mark.skip(reason="need creds")
def test_bq_pr_comment():
    bq = BQDriver()

    if (
        bq.bq_service.query(
            "select * from `test_dataset.testruns` where repoid = 2 limit 1"
        )
        == []
    ):
        populate_pr_comment_testruns(bq)

    pr_agg = bq.pr_comment_agg(repoid=2, commit_sha="abcde")
    assert pr_agg == [
        {
            "commit_sha": "abcde",
            "ct_passed": 6,
            "ct_failed": 3,
            "ct_skipped": 0,
            "ct_flaky_failed": 0,
        }
    ]

    pr_fail = bq.pr_comment_fail(repoid=2, commit_sha="abcde")
    assert len(pr_fail) == 3
    assert {t["computed_name"] for t in pr_fail} == {
        "pr_computed_name_1",
    }
    assert {t["failure_message"] for t in pr_fail} == {"hi"}
    assert {tuple(t["flags"]) for t in pr_fail} == {
        ("flag_1",),
        ("flag_2",),
        ("flag_0",),
    }


def populate_testruns_for_upload_testruns(dbsession, bq: BQDriver):
    testruns = []

    upload = UploadFactory()
    upload.id_ = 1
    dbsession.add(upload)
    dbsession.flush()

    testruns: list[test_results_parser.Testrun] = [
        {  # this test is flaky failure
            "name": "test_0",
            "classname": "class_0",
            "testsuite": "suite_upload",
            "duration": 0.0,
            "outcome": "failure",
            "filename": None,
            "computed_name": "upload_computed_name_0",
            "failure_message": None,
            "build_url": None,
        },
        {  # this test is just a failure
            "name": "test_1",
            "classname": "class_1",
            "testsuite": "suite_upload",
            "duration": 0.0,
            "outcome": "failure",
            "filename": None,
            "computed_name": "upload_computed_name_1",
            "failure_message": None,
            "build_url": None,
        },
        {  # this test is a pass but also flaky
            "name": "test_2",
            "classname": "class_2",
            "testsuite": "suite_upload",
            "duration": 0.0,
            "outcome": "pass",
            "filename": None,
            "computed_name": "upload_computed_name_2",
            "failure_message": None,
            "build_url": None,
        },
        {  # this test should be ignored
            "name": "test_3",
            "classname": "class_3",
            "testsuite": "suite_upload",
            "duration": 0.0,
            "outcome": "pass",
            "filename": None,
            "computed_name": "upload_computed_name_3",
            "failure_message": None,
            "build_url": None,
        },
    ]

    bq.write_testruns(None, 3, "abcde", "feature_branch", upload, "pytest", testruns)


@pytest.mark.skip(reason="need creds")
def test_bq_testruns_for_upload(dbsession):
    bq = BQDriver(
        {
            calc_test_id("test_0", "class_0", "suite_upload"),
            calc_test_id("test_2", "class_2", "suite_upload"),
        }
    )

    if (
        bq.bq_service.query(
            "select * from `test_dataset.testruns` where repoid = 3 limit 1"
        )
        == []
    ):
        populate_testruns_for_upload_testruns(dbsession, bq)

    testruns_for_upload = bq.testruns_for_upload(
        upload_id=1,
        test_ids=[
            calc_test_id("test_0", "class_0", "suite_upload"),
            calc_test_id("test_2", "class_2", "suite_upload"),
        ],
    )

    assert {t["test_id"] for t in testruns_for_upload} == {
        calc_test_id("test_0", "class_0", "suite_upload"),
        calc_test_id("test_2", "class_2", "suite_upload"),
        calc_test_id("test_1", "class_1", "suite_upload"),
    }

    assert {t["outcome"] for t in testruns_for_upload} == {3, 1, 0}


def populate_analytics_testruns(bq: BQDriver):
    upload_0 = UploadFactory()
    upload_0.report.commit.commitid = "abcde"
    upload_0.report.commit.branch = "feature_branch"
    upload_0.report.commit.repoid = 1
    upload_0.flags.append(RepositoryFlagFactory(flag_name="flag_0"))

    upload_1 = UploadFactory()
    upload_1.report.commit.commitid = "abcde"
    upload_1.report.commit.branch = "feature_branch"
    upload_1.report.commit.repoid = 1
    upload_1.flags.append(RepositoryFlagFactory(flag_name="flag_1"))

    testruns: list[test_results_parser.Testrun] = [
        {
            "name": "interval_start",
            "classname": "class_0",
            "testsuite": "suite_upload",
            "duration": 20000.0,
            "outcome": "failure",
            "filename": None,
            "computed_name": "upload_computed_name_0",
            "failure_message": None,
            "build_url": None,
        },
    ]

    timestamp = int((datetime.now() - timedelta(days=50)).timestamp() * 1000000)

    bq.write_testruns(
        timestamp, 1, "interval_start", "feature_branch", upload_0, "pytest", testruns
    )

    testruns: list[test_results_parser.Testrun] = [
        {
            "name": "interval_end",
            "classname": "class_0",
            "testsuite": "suite_upload",
            "duration": 20000.0,
            "outcome": "failure",
            "filename": None,
            "computed_name": "upload_computed_name_0",
            "failure_message": None,
            "build_url": None,
        },
    ]

    timestamp = int((datetime.now() - timedelta(days=1)).timestamp() * 1000000)

    bq.write_testruns(
        timestamp, 1, "interval_end", "feature_branch", upload_0, "pytest", testruns
    )

    testruns: list[test_results_parser.Testrun] = [
        {
            "name": "test_0",
            "classname": "class_0",
            "testsuite": "suite_upload",
            "duration": 10.0,
            "outcome": "failure",
            "filename": None,
            "computed_name": "upload_computed_name_0",
            "failure_message": None,
            "build_url": None,
        },
        {
            "name": "test_1",
            "classname": "class_1",
            "testsuite": "suite_upload",
            "duration": 10.0,
            "outcome": "pass",
            "filename": None,
            "computed_name": "upload_computed_name_1",
            "failure_message": None,
            "build_url": None,
        },
    ]

    timestamp = int((datetime.now() - timedelta(days=20)).timestamp() * 1000000)

    bq.write_testruns(
        timestamp, 1, "commit_1", "feature_branch", upload_0, "pytest", testruns
    )

    testruns: list[test_results_parser.Testrun] = [
        {
            "name": "test_1",
            "classname": "class_1",
            "testsuite": "suite_upload",
            "duration": 10.0,
            "outcome": "failure",
            "filename": None,
            "computed_name": "upload_computed_name_1",
            "failure_message": None,
            "build_url": None,
        },
    ]

    timestamp = int((datetime.now() - timedelta(days=20)).timestamp() * 1000000)

    bq.write_testruns(
        timestamp, 1, "commit_1", "feature_branch", upload_1, "pytest", testruns
    )

    bq = BQDriver(
        {
            calc_test_id("test_1", "class_1", "suite_upload"),
        }
    )

    testruns: list[test_results_parser.Testrun] = [
        {
            "name": "test_0",
            "classname": "class_0",
            "testsuite": "suite_upload",
            "duration": 20.0,
            "outcome": "pass",
            "filename": None,
            "computed_name": "upload_computed_name_0",
            "failure_message": None,
            "build_url": None,
        },
        {
            "name": "test_1",
            "classname": "class_1",
            "testsuite": "suite_upload",
            "duration": 10.0,
            "outcome": "failure",
            "filename": None,
            "computed_name": "upload_computed_name_1",
            "failure_message": None,
            "build_url": None,
        },
    ]

    timestamp = int((datetime.now() - timedelta(days=10)).timestamp() * 1000000)

    bq.write_testruns(
        timestamp, 1, "commit_2", "feature_branch", upload_1, "pytest", testruns
    )


@pytest.mark.skip(reason="need creds")
@time_machine.travel(datetime.now(tz=timezone.utc), tick=False)
def test_bq_analytics():
    bq = BQDriver()

    if (
        bq.bq_service.query(
            "select * from `test_dataset.testruns` where repoid = 1 limit 1"
        )
        == []
    ):
        populate_analytics_testruns(bq)

    testruns_for_upload = bq.analytics(1, 30, 7, "feature_branch")

    assert sorted(
        [(x | {"flags": sorted(x["flags"])}) for x in testruns_for_upload],
        key=lambda x: x["name"],
    ) == [
        {
            "name": "test_0",
            "classname": "class_0",
            "testsuite": "suite_upload",
            "computed_name": "upload_computed_name_0",
            "cwf": 1,
            "avg_duration": 15.0,
            "last_duration": 20.0,
            "pass_count": 1,
            "fail_count": 1,
            "skip_count": 0,
            "flaky_fail_count": 0,
            "updated_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "flags": ["flag_0", "flag_1"],
        },
        {
            "name": "test_1",
            "classname": "class_1",
            "testsuite": "suite_upload",
            "computed_name": "upload_computed_name_1",
            "cwf": 2,
            "avg_duration": 10.0,
            "last_duration": 10.0,
            "pass_count": 1,
            "fail_count": 1,
            "skip_count": 0,
            "flaky_fail_count": 1,
            "updated_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "flags": ["flag_0", "flag_1"],
        },
    ]
