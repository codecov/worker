import mock
import pytest
from shared.torngit.exceptions import TorngitClientError

from database.models.core import Commit
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


@pytest.mark.asyncio
async def test_send_to_provider():
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore
    tn.pull = mock.AsyncMock()
    tn.pull.database_pull.commentid = None
    tn.repo_service = mock.AsyncMock()
    m = dict(id=1)
    tn.repo_service.post_comment.return_value = m

    res = await tn.send_to_provider("hello world")

    assert res == True

    tn.repo_service.post_comment.assert_called_with(
        tn.pull.database_pull.pullid, "hello world"
    )
    assert tn.pull.database_pull.commentid == 1


@pytest.mark.asyncio
async def test_send_to_provider_edit():
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore
    tn.pull = mock.AsyncMock()
    tn.pull.database_pull.commentid = 1
    tn.repo_service = mock.AsyncMock()
    m = dict(id=1)
    tn.repo_service.edit_comment.return_value = m

    res = await tn.send_to_provider("hello world")

    assert res == True
    tn.repo_service.edit_comment.assert_called_with(
        tn.pull.database_pull.pullid, 1, "hello world"
    )


@pytest.mark.asyncio
async def test_send_to_provider_fail():
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore
    tn.pull = mock.AsyncMock()
    tn.pull.database_pull.commentid = 1
    tn.repo_service = mock.AsyncMock()
    m = dict(id=1)
    tn.repo_service.edit_comment.side_effect = TorngitClientError

    res = await tn.send_to_provider("hello world")

    assert res == False


def test_generate_failure_info():
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id, 1.0
    )

    res = generate_failure_info(fail)

    assert res == "  <pre>hello world</pre>"


def test_build_message():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id, 1.0
    )
    payload = TestResultsNotificationPayload(1, 2, 3, [fail], dict())
    tn = TestResultsNotifier(Commit(), None, payload)  # type:ignore
    res = tn.build_message()

    assert (
        res
        == """### :x: 1 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 3 | 1 | 2 | 3 |
<details><summary>View the top 1 failed tests by shortest run time</summary>

> <pre>
> testname
> </pre>
> <details><summary>Stack Traces | 1s run time</summary>
> 
> >   <pre>hello world</pre>
> 
> </details>

</details>"""
    )


def test_build_message_with_flake():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id, 1.0
    )

    payload = TestResultsNotificationPayload(
        1, 2, 3, [fail], {test_id: FlakeInfo(1, 3)}
    )
    tn = TestResultsNotifier(Commit(), None, payload)  # type:ignore
    res = tn.build_message()

    assert (
        res
        == """### :x: 1 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 3 | 1 | 2 | 3 |
<details><summary>View the top 1 failed tests by shortest run time</summary>

</details>
<details><summary>View the full list of 1 :snowflake: flaky tests</summary>

> <pre>
> testname
> </pre>
> **Flake rate in main:** 0.3333333333333333% (Passed 2 times, Failed 1 times)
> <details><summary>Stack Traces | 1s run time</summary>
> 
> >   <pre>hello world</pre>
> 
> </details>

</details>"""
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
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore

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
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore
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
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore

    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.AsyncMock(return_value=False)

    notification_result = await tn.notify()
    assert notification_result == NotifierResult.NO_PULL
