import mock
import pytest
from shared.torngit.exceptions import TorngitClientError

from database.models.core import Commit
from services.test_results import (
    TestResultsNotificationFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    generate_flags_hash,
    generate_test_id,
)


@pytest.fixture
def tn():
    commit = Commit()
    tn = TestResultsNotifier(commit=commit, commit_yaml=None)
    return tn


@pytest.mark.asyncio
async def test_send_to_provider(tn):
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
async def test_send_to_provider_edit(tn):
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
async def test_send_to_provider_fail(tn):
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
def test_generate_test_description(tn, testname, message):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", testname, flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", testname, [], test_id, None
    )
    res = tn.generate_test_description(fail)
    assert res == message


def test_generate_failure_info(tn):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id, None
    )

    res = tn.generate_failure_info(fail)

    assert res == "  <pre>hello world</pre>"


def test_build_message(tn):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id, None
    )
    payload = TestResultsNotificationPayload(1, 2, 3, [fail], None)
    res = tn.build_message(payload)

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


def test_build_message_with_flake(tn):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id, 1
    )

    payload = TestResultsNotificationPayload(1, 2, 3, [fail], {test_id})
    res = tn.build_message(payload)

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
async def test_notify(mocker, tn):
    mocker.patch(
        "services.test_results.get_repo_provider_service", return_value=mock.AsyncMock()
    )
    mocker.patch(
        "services.test_results.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.AsyncMock(),
    )
    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.AsyncMock()

    success, reason = await tn.notify(None)
    assert success == True
    assert reason == "comment_posted"


@pytest.mark.asyncio
async def test_notify_fail_torngit_error(mocker, tn):
    mocker.patch(
        "services.test_results.get_repo_provider_service", return_value=mock.AsyncMock()
    )
    mocker.patch(
        "services.test_results.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.AsyncMock(),
    )
    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.AsyncMock(return_value=False)

    success, reason = await tn.notify(None)
    assert success == False
    assert reason == "torngit_error"


@pytest.mark.asyncio
async def test_notify_fail_no_pull(mocker, tn):
    mocker.patch(
        "services.test_results.get_repo_provider_service", return_value=mock.AsyncMock()
    )
    mocker.patch(
        "services.test_results.fetch_and_update_pull_request_information_from_commit",
        return_value=None,
    )
    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.AsyncMock(return_value=False)

    success, reason = await tn.notify(None)
    assert success == False
    assert reason == "no_pull"
