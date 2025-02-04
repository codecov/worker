import base64
import json
import zlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from time_machine import travel

from database.models import DailyTestRollup, Test, TestInstance
from database.tests.factories import (
    CommitFactory,
    PullFactory,
    ReportFactory,
    RepositoryFactory,
    UploadFactory,
)
from services.repository import EnrichedPull
from services.seats import SeatActivationInfo
from services.urls import services_short_dict
from tasks.ta_finisher import TAFinisherTask
from tasks.ta_processor import TAProcessorTask
from tests.helpers import mock_all_plans_and_tiers

here = Path(__file__)


@pytest.fixture(autouse=True)
def mock_bigquery_service():
    with patch("ta_storage.bq.get_bigquery_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def mock_repo_provider_comments(mocker):
    m = mocker.MagicMock(
        edit_comment=AsyncMock(return_value=True),
        post_comment=AsyncMock(return_value={"id": 1}),
    )
    _ = mocker.patch(
        "tasks.ta_finisher.get_repo_provider_service",
        return_value=m,
    )
    return m


def generate_junit_xml(
    testruns: list[dict[str, Any]],
    testsuite_name: str = "hello_world",
) -> str:
    testcases = []

    num_total = len(testruns)
    num_fail = 0
    num_skip = 0
    num_error = 0
    total_time = 0

    for testrun in testruns:
        total_time += float(testrun["duration_seconds"])
        match testrun["outcome"]:
            case "fail":
                num_fail += 1
                testcases.append(
                    f'<testcase classname="tests.test_parsers.TestParsers" name="{testrun["name"]}" time="{testrun["duration_seconds"]}"><failure message="hello world"/></testcase>'
                )
            case "skip":
                num_skip += 1
                testcases.append(
                    f'<testcase classname="tests.test_parsers.TestParsers" name="{testrun["name"]}" time="{testrun["duration_seconds"]}"><skipped/></testcase>'
                )
            case "error":
                num_error += 1
                testcases.append(
                    f'<testcase classname="tests.test_parsers.TestParsers" name="{testrun["name"]}" time="{testrun["duration_seconds"]}"><error/></testcase>'
                )
            case "pass":
                testcases.append(
                    f'<testcase classname="tests.test_parsers.TestParsers" name="{testrun["name"]}" time="{testrun["duration_seconds"]}"></testcase>'
                )

    testsuite_section = [
        f'<testsuite name="{testsuite_name}" tests="{num_total}" failures="{num_fail}" errors="{num_error}" skipped="{num_skip}" time="{total_time}">',
        *testcases,
        "</testsuite>",
    ]

    header = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<testsuites>",
        *testsuite_section,
        "</testsuites>",
    ]

    return "\n".join(header)


@travel("2025-01-01T00:00:00Z", tick=False)
@pytest.mark.django_db
def test_test_analytics(
    dbsession,
    mocker,
    mock_storage,
    celery_app,
    snapshot,
    mock_repo_provider_comments,
):
    mock_all_plans_and_tiers()
    url = "literally/whatever"

    testruns = [
        {
            "name": "test_divide",
            "outcome": "fail",
            "duration_seconds": 0.001,
            "failure_message": "hello world",
        },
        {"name": "test_multiply", "outcome": "pass", "duration_seconds": 0.002},
        {"name": "test_add", "outcome": "skip", "duration_seconds": 0.003},
        {"name": "test_subtract", "outcome": "error", "duration_seconds": 0.004},
    ]

    content: str = generate_junit_xml(testruns)
    json_content: dict[str, Any] = {
        "test_results_files": [
            {
                "filename": "hello_world.junit.xml",
                "data": base64.b64encode(zlib.compress(content.encode())).decode(),
            }
        ],
    }
    mock_storage.write_file("archive", url, json.dumps(json_content).encode())
    repo = RepositoryFactory.create(
        repoid=1,
        owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
        owner__username="joseph-sentry",
        owner__service="github",
        name="codecov-demo",
    )
    dbsession.add(repo)
    dbsession.flush()
    commit = CommitFactory.create(
        message="hello world",
        commitid="cd76b0821854a780b60012aed85af0a8263004ad",
        repository=repo,
        branch="main",
    )
    dbsession.add(commit)
    dbsession.flush()
    report = ReportFactory.create(commit=commit)
    report.report_type = "test_results"
    dbsession.add(report)
    dbsession.flush()
    upload = UploadFactory.create(storage_path=url, report=report)
    dbsession.add(upload)
    dbsession.flush()
    upload.id_ = 1
    dbsession.flush()

    argument = {"url": url, "upload_id": upload.id_}

    mocker.patch.object(TAProcessorTask, "app", celery_app)
    mocker.patch.object(TAFinisherTask, "app", celery_app)

    celery_app.tasks = {
        "app.tasks.flakes.ProcessFlakesTask": mocker.MagicMock(),
        "app.tasks.cache_rollup.CacheTestRollupsTask": mocker.MagicMock(),
    }

    pull = PullFactory.create(repository=commit.repository, head=commit.commitid)
    dbsession.add(pull)
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )

    _ = mocker.patch(
        "tasks.ta_finisher.fetch_and_update_pull_request_information_from_commit",
        return_value=enriched_pull,
    )
    mocker.patch(
        "tasks.ta_finisher.determine_seat_activation",
        return_value=SeatActivationInfo(reason="public_repo"),
    )

    result = TAProcessorTask().run_impl(
        dbsession,
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
        argument=argument,
    )

    assert result is True

    tests = dbsession.query(Test).all()
    test_instances = dbsession.query(TestInstance).all()
    rollups = dbsession.query(DailyTestRollup).all()

    tests = [
        {
            "repoid": test.repoid,
            "name": test.name,
            "testsuite": test.testsuite,
            "flags_hash": test.flags_hash,
            "framework": test.framework,
            "computed_name": test.computed_name,
            "filename": test.filename,
        }
        for test in dbsession.query(Test).all()
    ]
    test_instances = [
        {
            "test_id": test_instance.test_id,
            "duration_seconds": test_instance.duration_seconds,
            "outcome": test_instance.outcome,
            "upload_id": test_instance.upload_id,
            "failure_message": test_instance.failure_message,
            "branch": test_instance.branch,
            "commitid": test_instance.commitid,
            "repoid": test_instance.repoid,
        }
        for test_instance in dbsession.query(TestInstance).all()
    ]
    rollups = [
        {
            "test_id": rollup.test_id,
            "date": rollup.date.isoformat(),
            "repoid": rollup.repoid,
            "branch": rollup.branch,
            "fail_count": rollup.fail_count,
            "flaky_fail_count": rollup.flaky_fail_count,
            "skip_count": rollup.skip_count,
            "pass_count": rollup.pass_count,
            "last_duration_seconds": rollup.last_duration_seconds,
            "avg_duration_seconds": rollup.avg_duration_seconds,
            "latest_run": rollup.latest_run.isoformat(),
            "commits_where_fail": rollup.commits_where_fail,
        }
        for rollup in dbsession.query(DailyTestRollup).all()
    ]

    assert snapshot("json") == {
        "tests": sorted(tests, key=lambda x: x["name"]),
        "test_instances": sorted(test_instances, key=lambda x: x["test_id"]),
        "rollups": sorted(rollups, key=lambda x: x["test_id"]),
    }

    result = TAFinisherTask().run_impl(
        dbsession,
        chord_result=[result],
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
    )

    assert result["notify_attempted"] is True
    assert result["notify_succeeded"] is True
    assert result["queue_notify"] is False

    mock_repo_provider_comments.post_comment.assert_called_once()

    short_form_service_name = services_short_dict.get(
        upload.report.commit.repository.owner.service
    )

    mock_repo_provider_comments.post_comment.assert_called_once_with(
        pull.pullid,
        f"""### :x: 2 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 3 | 2 | 1 | 1 |
<details><summary>View the top 2 failed test(s) by shortest run time</summary>

> 
> ```python
> tests.test_parsers.TestParsers test_divide
> ```
> 
> <details><summary>Stack Traces | 0.001s run time</summary>
> 
> > 
> > ```python
> > hello world
> > ```
> 
> </details>


> 
> ```python
> tests.test_parsers.TestParsers test_subtract
> ```
> 
> <details><summary>Stack Traces | 0.004s run time</summary>
> 
> > 
> > ```python
> > No failure message available
> > ```
> 
> </details>

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/{short_form_service_name}/{upload.report.commit.repository.owner.username}/{upload.report.commit.repository.name}/tests/{upload.report.commit.branch})
:loudspeaker:  Thoughts on this report? [Let us know!](https://github.com/codecov/feedback/issues/304)""",
    )
