import time
from datetime import datetime

import pytest
from django.db import connections
from shared.django_apps.timeseries.models import Testrun
from time_machine import travel

from services.test_analytics.ta_timeseries import (
    calc_test_id,
    get_pr_comment_agg,
    get_pr_comment_failures,
    get_summary,
    get_testrun_branch_summary_via_testrun,
    get_testruns_for_flake_detection,
    insert_testrun,
    update_testrun_to_flaky,
)


@pytest.mark.django_db(databases=["timeseries"])
def test_insert_testrun():
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag1", "flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "pass",
                    "testsuite": "test_suite",
                    "failure_message": None,
                    "filename": "test_filename",
                    "build_url": None,
                }
            ],
        },
    )

    t = Testrun.objects.get(
        name="test_name",
        classname="test_classname",
        testsuite="test_suite",
        failure_message=None,
        filename="test_filename",
    )
    assert t.outcome == "pass"


@pytest.mark.django_db(databases=["timeseries"])
def test_pr_comment_agg():
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag1", "flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "pass",
                    "testsuite": "test_suite",
                    "failure_message": None,
                    "filename": "test_filename",
                    "build_url": None,
                }
            ],
        },
    )

    agg = get_pr_comment_agg(1, "commit_sha")
    assert agg == {
        "pass": 1,
    }


@pytest.mark.django_db(databases=["timeseries"])
def test_pr_comment_failures():
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag1", "flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "failure",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                }
            ],
        },
    )

    failures = get_pr_comment_failures(1, "commit_sha")
    assert len(failures) == 1
    failure = failures[0]
    assert failure["test_id"] == calc_test_id(
        "test_name", "test_classname", "test_suite"
    )
    assert failure["computed_name"] == "computed_name"
    assert failure["failure_message"] == "failure_message"
    assert failure["duration_seconds"] == 1.0
    assert failure["upload_id"] == 1


@pytest.mark.django_db(databases=["timeseries"])
def test_get_testruns_for_flake_detection(db):
    test_ids = {calc_test_id("flaky_test_name", "test_classname", "test_suite")}
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag1", "flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "failure",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
                {
                    "name": "flaky_test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "failure",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
                {
                    "name": "flaky_test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "pass",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "pass",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
            ],
        },
        flaky_test_ids=test_ids,
    )

    testruns = get_testruns_for_flake_detection(1, test_ids)
    assert len(testruns) == 3
    assert testruns[0].outcome == "failure"
    assert testruns[0].failure_message == "failure_message"
    assert testruns[0].name == "test_name"
    assert testruns[1].outcome == "flaky_failure"
    assert testruns[1].failure_message == "failure_message"
    assert testruns[1].name == "flaky_test_name"
    assert testruns[2].outcome == "pass"
    assert testruns[2].failure_message == "failure_message"
    assert testruns[2].name == "flaky_test_name"


@pytest.mark.django_db(databases=["timeseries"])
@travel(datetime(2025, 1, 1), tick=False)
def test_update_testrun_to_flaky():
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag1", "flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "failure",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
            ],
        },
    )
    update_testrun_to_flaky(
        datetime.now(),
        calc_test_id("test_name", "test_classname", "test_suite"),
    )
    testrun = Testrun.objects.get(
        name="test_name",
        classname="test_classname",
        testsuite="test_suite",
    )
    assert testrun.outcome == "flaky_failure"


@pytest.mark.integration
@pytest.mark.django_db(databases=["timeseries"], transaction=True)
def test_get_testrun_summary():
    connection = connections["timeseries"]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE TABLE timeseries_testrun;
            TRUNCATE TABLE timeseries_testrun_summary_1day;
            """
        )
        cursor.execute(
            """
            SELECT remove_continuous_aggregate_policy('timeseries_testrun_summary_1day');
            select add_continuous_aggregate_policy(
                'timeseries_testrun_summary_1day',
                start_offset => '7 days',
                end_offset => NULL,
                schedule_interval => INTERVAL '1 milliseconds'
            );
            """
        )

    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag1"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "pass",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
            ],
        },
    )
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag1", "flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name2",
                    "classname": "test_classname2",
                    "computed_name": "computed_name2",
                    "duration": 1.0,
                    "outcome": "pass",
                    "testsuite": "test_suite2",
                    "failure_message": "failure_message2",
                    "filename": "test_filename2",
                    "build_url": None,
                },
            ],
        },
    )

    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha",
        branch="branch",
        upload_id=1,
        flags=["flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 3.0,
                    "outcome": "failure",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
            ],
        },
    )

    time.sleep(5)

    summaries = get_summary(1)
    assert len(summaries) == 2
    assert summaries[0].testsuite == "test_suite"
    assert summaries[0].classname == "test_classname"
    assert summaries[0].name == "test_name"
    assert summaries[0].avg_duration_seconds == 2.0
    assert summaries[0].last_duration_seconds == 3.0
    assert summaries[0].pass_count == 1
    assert summaries[0].fail_count == 1
    assert summaries[0].flaky_fail_count == 0
    assert summaries[0].skip_count == 0
    assert summaries[0].flags == ["flag1", "flag2"]

    assert summaries[1].testsuite == "test_suite2"
    assert summaries[1].classname == "test_classname2"
    assert summaries[1].name == "test_name2"
    assert summaries[1].avg_duration_seconds == 1.0
    assert summaries[1].last_duration_seconds == 1.0
    assert summaries[1].pass_count == 1
    assert summaries[1].fail_count == 0
    assert summaries[1].flaky_fail_count == 0
    assert summaries[1].skip_count == 0
    assert summaries[1].flags == ["flag1", "flag2"]

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT remove_continuous_aggregate_policy('timeseries_testrun_summary_1day');
            select add_continuous_aggregate_policy(
                'timeseries_testrun_summary_1day',
                start_offset => '7 days',
                end_offset => '1 days',
                schedule_interval => INTERVAL '1 days'
            );
            """
        )


@pytest.mark.integration
@pytest.mark.django_db(databases=["timeseries"], transaction=True)
def test_get_testrun_branch_summary_via_testrun():
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha1",
        branch="feature-branch",
        upload_id=1,
        flags=["flag1"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 1.0,
                    "outcome": "pass",
                    "testsuite": "test_suite",
                    "failure_message": None,
                    "filename": "test_filename",
                    "build_url": None,
                },
            ],
        },
    )

    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha2",
        branch="feature-branch",
        upload_id=2,
        flags=["flag1", "flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 3.0,
                    "outcome": "failure",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
            ],
        },
    )

    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha2",
        branch="feature-branch",
        upload_id=2,
        flags=["flag2"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name2",
                    "classname": "test_classname2",
                    "computed_name": "computed_name2",
                    "duration": 2.0,
                    "outcome": "pass",
                    "testsuite": "test_suite2",
                    "failure_message": None,
                    "filename": "test_filename2",
                    "build_url": None,
                },
            ],
        },
    )

    # Add a test on a different branch that should not be included
    insert_testrun(
        timestamp=datetime.now(),
        repo_id=1,
        commit_sha="commit_sha3",
        branch="other-branch",
        upload_id=3,
        flags=["flag1"],
        parsing_info={
            "framework": "Pytest",
            "testruns": [
                {
                    "name": "test_name",
                    "classname": "test_classname",
                    "computed_name": "computed_name",
                    "duration": 5.0,
                    "outcome": "failure",
                    "testsuite": "test_suite",
                    "failure_message": "failure_message",
                    "filename": "test_filename",
                    "build_url": None,
                },
            ],
        },
    )

    summaries = get_testrun_branch_summary_via_testrun(1, "feature-branch")
    assert len(summaries) == 2

    # Check first test summary
    first_test = next(s for s in summaries if s.name == "test_name")
    assert first_test.testsuite == "test_suite"
    assert first_test.classname == "test_classname"
    assert first_test.computed_name == "computed_name"
    assert first_test.failing_commits == 1  # One commit had a failure
    assert first_test.last_duration_seconds == 3.0  # Last run was 3.0
    assert first_test.avg_duration_seconds == 2.0  # Average of 1.0 and 3.0
    assert first_test.pass_count == 1
    assert first_test.fail_count == 1
    assert first_test.skip_count == 0
    assert first_test.flaky_fail_count == 0
    assert sorted(first_test.flags) == ["flag1", "flag2"]

    # Check second test summary
    second_test = next(s for s in summaries if s.name == "test_name2")
    assert second_test.testsuite == "test_suite2"
    assert second_test.classname == "test_classname2"
    assert second_test.computed_name == "computed_name2"
    assert second_test.failing_commits == 0  # No failures
    assert second_test.last_duration_seconds == 2.0
    assert second_test.avg_duration_seconds == 2.0
    assert second_test.pass_count == 1
    assert second_test.fail_count == 0
    assert second_test.skip_count == 0
    assert second_test.flaky_fail_count == 0
    assert second_test.flags == ["flag2"]
