import mock
import pytest
from shared.torngit.exceptions import TorngitClientError

from database.tests.factories import CommitFactory
from helpers.notifier import NotifierResult
from services.test_results import (
    FlakeInfo,
    TestResultsNotificationFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    generate_failure_info,
    generate_flags_hash,
    generate_test_id,
)
from services.urls import services_short_dict


@pytest.mark.asyncio
async def test_send_to_provider():
    tn = TestResultsNotifier(CommitFactory(), None)
    tn._pull = mock.AsyncMock()
    tn._pull.database_pull.commentid = None
    tn._repo_service = mock.AsyncMock()
    m = dict(id=1)
    tn._repo_service.post_comment.return_value = m

    res = await tn.send_to_provider(tn._pull, "hello world")

    assert res == True

    tn._repo_service.post_comment.assert_called_with(
        tn._pull.database_pull.pullid, "hello world"
    )
    assert tn._pull.database_pull.commentid == 1


@pytest.mark.asyncio
async def test_send_to_provider_edit():
    tn = TestResultsNotifier(CommitFactory(), None)
    tn._pull = mock.AsyncMock()
    tn._pull.database_pull.commentid = 1
    tn._repo_service = mock.AsyncMock()
    m = dict(id=1)
    tn._repo_service.edit_comment.return_value = m

    res = await tn.send_to_provider(tn._pull, "hello world")

    assert res == True
    tn._repo_service.edit_comment.assert_called_with(
        tn._pull.database_pull.pullid, 1, "hello world"
    )


@pytest.mark.asyncio
async def test_send_to_provider_fail():
    tn = TestResultsNotifier(CommitFactory(), None)
    tn._pull = mock.AsyncMock()
    tn._pull.database_pull.commentid = 1
    tn._repo_service = mock.AsyncMock()
    m = dict(id=1)
    tn._repo_service.edit_comment.side_effect = TorngitClientError

    res = await tn.send_to_provider(tn._pull, "hello world")

    assert res == False


def test_generate_failure_info():
    tn = TestResultsNotifier(CommitFactory(), None)
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world",
        "testsuite",
        "testname",
        [],
        test_id,
        1.0,
        "https://example.com/build_url",
    )

    res = generate_failure_info(fail)

    assert (
        res
        == """
```
hello world
```

[View](https://example.com/build_url) the CI Build"""
    )


def test_build_message():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world",
        "testsuite",
        "testname",
        [],
        test_id,
        1.0,
        "https://example.com/build_url",
    )
    payload = TestResultsNotificationPayload(1, 2, 3, [fail], dict())
    commit = CommitFactory()
    tn = TestResultsNotifier(commit, None, None, None, payload)
    res = tn.build_message()

    assert (
        res
        == f"""### :x: 1 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 3 | 1 | 2 | 3 |
<details><summary>View the top 1 failed tests by shortest run time</summary>

> 
> ```
> testname
> ```
> 
> <details><summary>Stack Traces | 1s run time</summary>
> 
> > 
> > ```
> > hello world
> > ```
> > 
> > [View](https://example.com/build_url) the CI Build
> 
> </details>

</details>

To view individual test run time comparison to the main branch, go to the [Test Analytics Dashboard](https://app.codecov.io/{services_short_dict.get(commit.repository.service)}/{commit.repository.owner.username}/{commit.repository.name}/tests/{commit.branch})"""
    )


def test_build_message_with_flake():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world",
        "testsuite",
        "testname",
        [],
        test_id,
        1.0,
        "https://example.com/build_url",
    )

    payload = TestResultsNotificationPayload(
        1, 2, 3, [fail], {test_id: FlakeInfo(1, 3)}
    )
    commit = CommitFactory(branch="test_branch")
    tn = TestResultsNotifier(commit, None, None, None, payload)
    res = tn.build_message()

    assert (
        res
        == f"""### :x: 1 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 3 | 1 | 2 | 3 |
<details><summary>View the full list of 1 :snowflake: flaky tests</summary>

> 
> ```
> testname
> ```
> 
> **Flake rate in main:** 33.33% (Passed 2 times, Failed 1 times)
> <details><summary>Stack Traces | 1s run time</summary>
> 
> > 
> > ```
> > hello world
> > ```
> > 
> > [View](https://example.com/build_url) the CI Build
> 
> </details>

</details>

To view individual test run time comparison to the main branch, go to the [Test Analytics Dashboard](https://app.codecov.io/{services_short_dict.get(commit.repository.service)}/{commit.repository.owner.username}/{commit.repository.name}/tests/{commit.branch})"""
    )


@pytest.mark.asyncio
async def test_notify(mocker):
    mocker.patch(
        "helpers.notifier.get_repo_provider_service", return_value=mock.AsyncMock()
    )
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.AsyncMock(),
    )
    tn = TestResultsNotifier(CommitFactory(), None)

    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.AsyncMock()

    notification_result = await tn.notify()

    assert notification_result == NotifierResult.COMMENT_POSTED


@pytest.mark.asyncio
async def test_notify_fail_torngit_error(
    mocker,
):
    mocker.patch(
        "helpers.notifier.get_repo_provider_service", return_value=mock.AsyncMock()
    )
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.AsyncMock(),
    )
    tn = TestResultsNotifier(CommitFactory(), None)
    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.AsyncMock(return_value=False)

    notification_result = await tn.notify()

    assert notification_result == NotifierResult.TORNGIT_ERROR


@pytest.mark.asyncio
async def test_notify_fail_no_pull(
    mocker,
):
    mocker.patch(
        "helpers.notifier.get_repo_provider_service", return_value=mock.AsyncMock()
    )
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=None,
    )
    tn = TestResultsNotifier(CommitFactory(), None)

    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.AsyncMock(return_value=False)

    notification_result = await tn.notify()
    assert notification_result == NotifierResult.NO_PULL
