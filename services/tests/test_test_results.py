import mock
import pytest
from shared.torngit.exceptions import TorngitClientError

from database.enums import FlakeSymptomType
from database.models.core import Commit
from services.test_results import (
    TestResultsNotificationFailure,
    TestResultsNotificationFlake,
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


def test_generate_test_description(tn):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )
    res = tn.generate_test_description(fail)
    assert (
        res
        == "<pre>**Testsuite:**<br>testsuite<br><br>**Test name:**<br>testname<br><br>**Envs:**<br>- default<br></pre>"
    )


@pytest.mark.parametrize(
    "is_new_flake,flake_header",
    [(False, "Known Flaky Test"), (True, "Newly Detected Flake")],
)
def test_generate_test_description_with_flake(tn, is_new_flake, flake_header):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )
    flake = TestResultsNotificationFlake(
        [],
        is_new_flake,
    )
    res = tn.generate_test_description(fail, flake)
    assert (
        res
        == f":snowflake::card_index_dividers: **{flake_header}**<br><pre>**Testsuite:**<br>testsuite<br><br>**Test name:**<br>testname<br><br>**Envs:**<br>- default<br></pre>"
    )


def test_generate_failure_info(tn):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )

    res = tn.generate_failure_info(fail)

    assert res == "<pre>hello world</pre>"


@pytest.mark.parametrize(
    "flake_symptoms,message",
    [
        (
            [FlakeSymptomType.FAILED_IN_DEFAULT_BRANCH],
            ":snowflake: :card_index_dividers: **Failure on default branch**<br><pre>hello world</pre>",
        ),
        (
            [
                FlakeSymptomType.FAILED_IN_DEFAULT_BRANCH,
                FlakeSymptomType.UNRELATED_MATCHING_FAILURES,
            ],
            ":snowflake: :card_index_dividers: **Failure on default branch**<br>:snowflake: :card_index_dividers: **Matching failures on unrelated branches**<br><pre>hello world</pre>",
        ),
    ],
)
def test_generate_failure_info_with_flake(tn, flake_symptoms, message):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )
    flake = TestResultsNotificationFlake(flake_symptoms, True)

    res = tn.generate_failure_info(fail, flake)
    assert res == message


def test_build_message(tn):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )
    payload = TestResultsNotificationPayload(1, 2, 3, [fail], None)
    res = tn.build_message(payload)

    assert (
        res
        == """**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.

### :x: Failed Test Results: 
Completed 6 tests with **`1 failed`**, 2 passed and 3 skipped.
<details><summary>View the full list of failed tests</summary>

| **Test Description** | **Failure message** |
| :-- | :-- |
| <pre>**Testsuite:**<br>testsuite<br><br>**Test name:**<br>testname<br><br>**Envs:**<br>- default<br></pre> | <pre>hello world</pre> |"""
    )


def test_build_message_with_flake(tn):
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world", "testsuite", "testname", [], test_id
    )
    flake = TestResultsNotificationFlake(
        [FlakeSymptomType.FAILED_IN_DEFAULT_BRANCH],
        True,
    )
    payload = TestResultsNotificationPayload(1, 2, 3, [fail], {test_id: flake})
    res = tn.build_message(payload)

    assert (
        res
        == """**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.

### :x: Failed Test Results: 
Completed 6 tests with **`1 failed`**(1 newly detected flaky), 2 passed and 3 skipped.
- Total :snowflake:**1 flaky tests.**
<details><summary>View the full list of failed tests</summary>

| **Test Description** | **Failure message** |
| :-- | :-- |
| :snowflake::card_index_dividers: **Newly Detected Flake**<br><pre>**Testsuite:**<br>testsuite<br><br>**Test name:**<br>testname<br><br>**Envs:**<br>- default<br></pre> | :snowflake: :card_index_dividers: **Failure on default branch**<br><pre>hello world</pre> |"""
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
