import mock
import pytest
from shared.torngit.exceptions import TorngitClientError

from database.models.core import Commit
from helpers.notifier import NotifierResult
from services.test_results import (
    TestResultsNotificationFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
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


@pytest.mark.parametrize(
    "testname,message",
    [
        ("testname", "- **Test name:** testname<br><br>"),
        (
            "Test\x1ftestname",
            "- **Class name:** Test<br>**Test name:** testname<br><br>",
        ),
    ],
)
def test_generate_test_description(testname, message):
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", testname, flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", testname, [], test_id
    )
    res = tn.generate_test_description(fail)
    assert res == message


def test_generate_failure_info():
    tn = TestResultsNotifier(Commit(), None, None)  # type:ignore
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )

    res = tn.generate_failure_info(fail)

    assert res == "  <pre>hello world</pre>"


def test_build_message():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )
    payload = TestResultsNotificationPayload(1, 2, 3, [fail], None)
    tn = TestResultsNotifier(Commit(), None, payload)  # type:ignore
    res = tn.build_message()

    assert (
        res
        == """**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.

### :x: Failed Test Results: 
Completed 6 tests with **`1 failed`**, 2 passed and 3 skipped.
<details><summary>View the full list of failed tests</summary>

## testsuite
- **Test name:** testname<br><br>
  <pre>hello world</pre>
</details>"""
    )


def test_build_message_with_flake():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )

    payload = TestResultsNotificationPayload(1, 2, 3, [fail], {test_id})
    tn = TestResultsNotifier(Commit(), None, payload)  # type:ignore
    res = tn.build_message()

    assert (
        res
        == """**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.

### :x: Failed Test Results: 
Completed 6 tests with **`1 failed`**(1 known flakes hit), 2 passed and 3 skipped.
<details><summary>View the full list of flaky tests</summary>

## testsuite
- **Test name:** testname<br><br>
  <pre>hello world</pre>
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
