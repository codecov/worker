import base64
import json
import zlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import msgpack
import pytest

from database.models import Commit, DailyTestRollup, Test, TestInstance, Upload
from database.tests.factories import CommitFactory, UploadFactory
from services.redis import get_redis_connection
from services.urls import services_short_dict
from tasks.ta_finisher import TAFinisherTask
from tasks.ta_processor import TAProcessorTask

here = Path(__file__)


upload_idx = 0


@pytest.fixture
def generate_junit(mock_storage, dbsession):
    def _generate_junit(
        testruns: list[dict[str, Any]] | None = None,
        testsuite_name: str = "hello_world",
        raw: str | None = None,
        commit: Commit | None = None,
    ) -> Upload:
        assert raw or testruns

        global upload_idx
        url = f"literally/whatever/{upload_idx}"
        upload_idx += 1

        if raw is None:
            if not testruns:
                raise ValueError("generate_junit fixture: testruns must be provided")
            content = generate_junit_xml(testruns, testsuite_name)
        else:
            content = raw

        json_content: dict[str, Any] = {
            "test_results_files": [
                {
                    "filename": "hello_world.junit.xml",
                    "data": base64.b64encode(zlib.compress(content.encode())).decode(),
                }
            ],
        }

        mock_storage.write_file("archive", url, json.dumps(json_content).encode())
        upload = UploadFactory.create(storage_path=url)
        if commit:
            upload.report.commit = commit
        dbsession.add(upload)
        dbsession.flush()
        upload.report.commit.branch = "main"
        upload.report.report_type = "test_results"
        dbsession.flush()

        return upload

    return _generate_junit


@pytest.fixture
def mock_repo_provider_service(mocker):
    mock_repo_provider_service = AsyncMock()
    mocker.patch(
        "tasks.ta_finisher.get_repo_provider_service",
        return_value=mock_repo_provider_service,
    )
    mocker.patch(
        "helpers.notifier.get_repo_provider_service",
        return_value=mock_repo_provider_service,
    )
    return mock_repo_provider_service


@pytest.fixture
def mock_pull_request_information(mocker):
    mock_pull_request_information = AsyncMock()
    mocker.patch(
        "tasks.ta_finisher.fetch_and_update_pull_request_information_from_commit",
        return_value=mock_pull_request_information,
    )
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=mock_pull_request_information,
    )
    return mock_pull_request_information


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


def test_test_analytics(
    dbsession,
    mocker,
    mock_storage,
    celery_app,
    mock_repo_provider_service,
    mock_pull_request_information,
    generate_junit,
):
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

    upload = generate_junit(testruns)

    argument = {"url": upload.storage_path, "upload_id": upload.id_}

    mocker.patch.object(TAProcessorTask, "app", celery_app)
    mocker.patch.object(TAFinisherTask, "app", celery_app)

    celery_app.tasks = {
        "app.tasks.flakes.ProcessFlakesTask": mocker.MagicMock(),
        "app.tasks.cache_rollup.CacheTestRollupsTask": mocker.MagicMock(),
    }

    result = TAProcessorTask().run_impl(
        dbsession,
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
        argument=argument,
    )

    assert result is True
    redis = get_redis_connection()
    redis_results = redis.get(
        f"ta/intermediate/{upload.report.commit.repoid}/{upload.report.commit.commitid}/{upload.id_}"
    )
    assert redis_results is not None

    unpacked_results = msgpack.unpackb(redis_results)
    assert unpacked_results == [
        {
            "framework": None,
            "testruns": [
                {
                    "name": "test_divide",
                    "classname": "tests.test_parsers.TestParsers",
                    "duration": 0.001,
                    "outcome": "failure",
                    "testsuite": "hello_world",
                    "failure_message": "hello world",
                    "filename": None,
                    "build_url": None,
                    "computed_name": None,
                },
                {
                    "name": "test_multiply",
                    "classname": "tests.test_parsers.TestParsers",
                    "duration": 0.002,
                    "outcome": "pass",
                    "testsuite": "hello_world",
                    "failure_message": None,
                    "filename": None,
                    "build_url": None,
                    "computed_name": None,
                },
                {
                    "name": "test_add",
                    "classname": "tests.test_parsers.TestParsers",
                    "duration": 0.003,
                    "outcome": "skip",
                    "testsuite": "hello_world",
                    "failure_message": None,
                    "filename": None,
                    "build_url": None,
                    "computed_name": None,
                },
                {
                    "name": "test_subtract",
                    "classname": "tests.test_parsers.TestParsers",
                    "duration": 0.004,
                    "outcome": "error",
                    "testsuite": "hello_world",
                    "failure_message": None,
                    "filename": None,
                    "build_url": None,
                    "computed_name": None,
                },
            ],
        }
    ]

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

    mock_repo_provider_service.edit_comment.assert_called_once()

    short_form_service_name = services_short_dict.get(
        upload.report.commit.repository.owner.service
    )

    mock_repo_provider_service.edit_comment.assert_called_once_with(
        mock_pull_request_information.database_pull.pullid,
        mock_pull_request_information.database_pull.commentid,
        f"""### :x: 2 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 3 | 2 | 1 | 1 |
<details><summary>View the top 2 failed tests by shortest run time</summary>

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

    tests = dbsession.query(Test).all()
    assert len(tests) == 4

    test_instances = dbsession.query(TestInstance).all()
    assert len(test_instances) == 4

    rollups = dbsession.query(DailyTestRollup).all()
    assert len(rollups) == 4

    assert sorted(rollup.pass_count for rollup in rollups) == [0, 0, 0, 1]
    assert sorted(rollup.fail_count for rollup in rollups) == [0, 0, 1, 1]
    assert sorted(rollup.flaky_fail_count for rollup in rollups) == [0, 0, 0, 0]
    assert sorted(rollup.avg_duration_seconds for rollup in rollups) == [
        0.001,
        0.002,
        0.003,
        0.004,
    ]
    assert sorted(rollup.last_duration_seconds for rollup in rollups) == [
        0.001,
        0.002,
        0.003,
        0.004,
    ]


def test_test_analytics_error_comment(
    dbsession,
    mocker,
    mock_storage,
    celery_app,
    mock_repo_provider_service,
    mock_pull_request_information,
    generate_junit,
):
    wrong_xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite>
        <testcase time="0.001">
            <failure message="hello world"/>
        </testcase>
    </testsuite>
</testsuites>
"""
    upload = generate_junit(raw=wrong_xml)

    argument = {"url": upload.storage_path, "upload_id": upload.id_}

    mocker.patch.object(TAProcessorTask, "app", celery_app)
    mocker.patch.object(TAFinisherTask, "app", celery_app)

    result = TAProcessorTask().run_impl(
        dbsession,
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
        argument=argument,
    )

    assert result is False

    result = TAFinisherTask().run_impl(
        dbsession,
        chord_result=[result],
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
    )

    assert result["notify_attempted"] is False
    assert result["notify_succeeded"] is False
    assert result["queue_notify"] is True

    mock_repo_provider_service.edit_comment.assert_called_once()
    mock_repo_provider_service.edit_comment.assert_called_once_with(
        mock_pull_request_information.database_pull.pullid,
        mock_pull_request_information.database_pull.commentid,
        """### :x: Unsupported file format

> Upload processing failed due to unsupported file format. Please review the parser error message:
> `Error parsing JUnit XML in hello_world.junit.xml at 4:32: ParserError: No name found`
> For more help, visit our [troubleshooting guide](https://docs.codecov.com/docs/test-analytics#troubleshooting).
""",
    )

    tests = dbsession.query(Test).all()
    assert len(tests) == 0

    test_instances = dbsession.query(TestInstance).all()
    assert len(test_instances) == 0

    rollups = dbsession.query(DailyTestRollup).all()
    assert len(rollups) == 0


def test_test_analytics_regular_comment_with_error(
    dbsession,
    mocker,
    mock_storage,
    celery_app,
    mock_repo_provider_service,
    mock_pull_request_information,
    generate_junit,
):
    mocker.patch.object(TAProcessorTask, "app", celery_app)
    mocker.patch.object(TAFinisherTask, "app", celery_app)

    commit = CommitFactory.create()

    wrong_xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite>
        <testcase time="0.001">
            <failure message="hello world"/>
        </testcase>
    </testsuite>
</testsuites>
"""

    upload = generate_junit(raw=wrong_xml, commit=commit)
    argument = {"url": upload.storage_path, "upload_id": upload.id_}
    first_result = TAProcessorTask().run_impl(
        dbsession,
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
        argument=argument,
    )
    assert first_result is False

    testruns = [
        {
            "name": "test_divide",
            "outcome": "fail",
            "duration_seconds": 0.001,
            "failure_message": "hello world",
        },
    ]

    upload = generate_junit(testruns, commit=commit)
    argument = {"url": upload.storage_path, "upload_id": upload.id_}
    second_result = TAProcessorTask().run_impl(
        dbsession,
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
        argument=argument,
    )
    assert second_result is True

    result = TAFinisherTask().run_impl(
        dbsession,
        chord_result=[first_result, second_result],
        repoid=upload.report.commit.repoid,
        commitid=upload.report.commit.commitid,
        commit_yaml={"codecov": {"max_report_age": False}},
    )

    assert result["notify_attempted"] is True
    assert result["notify_succeeded"] is True
    assert result["queue_notify"] is False

    short_form_service_name = services_short_dict.get(
        upload.report.commit.repository.owner.service
    )

    mock_repo_provider_service.edit_comment.assert_called_once()
    mock_repo_provider_service.edit_comment.assert_called_once_with(
        mock_pull_request_information.database_pull.pullid,
        mock_pull_request_information.database_pull.commentid,
        f"""### :x: Unsupported file format

> Upload processing failed due to unsupported file format. Please review the parser error message:
> `Error parsing JUnit XML in hello_world.junit.xml at 4:32: ParserError: No name found`
> For more help, visit our [troubleshooting guide](https://docs.codecov.com/docs/test-analytics#troubleshooting).

---
### :x: 1 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 1 | 1 | 0 | 0 |
<details><summary>View the top 1 failed tests by shortest run time</summary>

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

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/{short_form_service_name}/{upload.report.commit.repository.owner.username}/{upload.report.commit.repository.name}/tests/{upload.report.commit.branch})
:loudspeaker:  Thoughts on this report? [Let us know!](https://github.com/codecov/feedback/issues/304)""",
    )

    tests = dbsession.query(Test).all()
    assert len(tests) == 1

    test_instances = dbsession.query(TestInstance).all()
    assert len(test_instances) == 1

    rollups = dbsession.query(DailyTestRollup).all()
    assert len(rollups) == 1
