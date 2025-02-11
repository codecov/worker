import mock
import pytest
from shared.plan.constants import DEFAULT_FREE_PLAN
from shared.torngit.exceptions import TorngitClientError

from database.models import UploadError
from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    RepositoryFactory,
    UploadFactory,
)
from helpers.notifier import NotifierResult
from services.test_results import (
    FlakeInfo,
    TACommentInDepthInfo,
    TestResultsNotificationFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    generate_failure_info,
    generate_flags_hash,
    generate_test_id,
    should_do_flaky_detection,
)
from services.urls import services_short_dict
from services.yaml import UserYaml
from tests.helpers import mock_all_plans_and_tiers


def mock_repo_service():
    repo_service = mock.Mock(
        post_comment=mock.AsyncMock(),
        edit_comment=mock.AsyncMock(),
    )
    return repo_service


def test_send_to_provider():
    tn = TestResultsNotifier(CommitFactory(), None)
    tn._pull = mock.Mock()
    tn._pull.database_pull.commentid = None
    tn._repo_service = mock_repo_service()
    m = dict(id=1)
    tn._repo_service.post_comment.return_value = m

    res = tn.send_to_provider(tn._pull, "hello world")

    assert res == True

    tn._repo_service.post_comment.assert_called_with(
        tn._pull.database_pull.pullid, "hello world"
    )
    assert tn._pull.database_pull.commentid == 1


def test_send_to_provider_edit():
    tn = TestResultsNotifier(CommitFactory(), None)
    tn._pull = mock.Mock()
    tn._pull.database_pull.commentid = 1
    tn._repo_service = mock_repo_service()
    m = dict(id=1)
    tn._repo_service.edit_comment.return_value = m

    res = tn.send_to_provider(tn._pull, "hello world")

    assert res == True
    tn._repo_service.edit_comment.assert_called_with(
        tn._pull.database_pull.pullid, 1, "hello world"
    )


def test_send_to_provider_fail():
    tn = TestResultsNotifier(CommitFactory(), None)
    tn._pull = mock.Mock()
    tn._pull.database_pull.commentid = 1
    tn._repo_service = mock_repo_service()
    tn._repo_service.edit_comment.side_effect = TorngitClientError

    res = tn.send_to_provider(tn._pull, "hello world")

    assert res == False


def test_generate_failure_info():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world",
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
```python
hello world
```

[View](https://example.com/build_url) the CI Build"""
    )


def test_build_message():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world",
        "testname",
        [],
        test_id,
        1.0,
        "https://example.com/build_url",
    )
    info = TACommentInDepthInfo(failures=[fail], flaky_tests={})
    payload = TestResultsNotificationPayload(1, 2, 3, info)
    commit = CommitFactory(branch="thing/thing")
    tn = TestResultsNotifier(commit, None, None, None, payload)
    res = tn.build_message()

    assert (
        res
        == f"""### :x: 1 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 3 | 1 | 2 | 3 |
<details><summary>View the top 1 failed test(s) by shortest run time</summary>

> 
> ```python
> testname
> ```
> 
> <details><summary>Stack Traces | 1s run time</summary>
> 
> > 
> > ```python
> > hello world
> > ```
> > 
> > [View](https://example.com/build_url) the CI Build
> 
> </details>

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/{services_short_dict.get(commit.repository.service)}/{commit.repository.owner.username}/{commit.repository.name}/tests/thing%2Fthing)
<sub>📋 Got 3 mins? [Take this short survey](https://forms.gle/BpocVj23nhr2Y45G7) to help us improve Test Analytics.</sub>"""
    )


def test_build_message_with_flake():
    flags_hash = generate_flags_hash([])
    test_id = generate_test_id(1, "testsuite", "testname", flags_hash)
    fail = TestResultsNotificationFailure(
        "hello world",
        "testname",
        [],
        test_id,
        1.0,
        "https://example.com/build_url",
    )
    flaky_test = FlakeInfo(1, 3)
    info = TACommentInDepthInfo(failures=[fail], flaky_tests={test_id: flaky_test})
    payload = TestResultsNotificationPayload(1, 2, 3, info)
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
> ```python
> testname
> ```
> 
> **Flake rate in main:** 33.33% (Passed 2 times, Failed 1 times)
> <details><summary>Stack Traces | 1s run time</summary>
> 
> > 
> > ```python
> > hello world
> > ```
> > 
> > [View](https://example.com/build_url) the CI Build
> 
> </details>

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/{services_short_dict.get(commit.repository.service)}/{commit.repository.owner.username}/{commit.repository.name}/tests/{commit.branch})
<sub>📋 Got 3 mins? [Take this short survey](https://forms.gle/BpocVj23nhr2Y45G7) to help us improve Test Analytics.</sub>"""
    )


def test_notify(mocker):
    mocker.patch("helpers.notifier.get_repo_provider_service", return_value=mock.Mock())
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.Mock(),
    )
    tn = TestResultsNotifier(CommitFactory(), None, _pull=mock.Mock())
    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.Mock()

    notification_result = tn.notify()

    assert notification_result == NotifierResult.COMMENT_POSTED


def test_notify_fail_torngit_error(
    mocker,
):
    mocker.patch("helpers.notifier.get_repo_provider_service", return_value=mock.Mock())
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.Mock(),
    )
    tn = TestResultsNotifier(CommitFactory(), None, _pull=mock.Mock())
    tn.build_message = mock.Mock()
    tn.send_to_provider = mock.Mock(return_value=False)

    notification_result = tn.notify()

    assert notification_result == NotifierResult.TORNGIT_ERROR


@pytest.mark.django_db
@pytest.mark.parametrize(
    "config,feature_flag,private,plan,ex_result",
    [
        (False, True, False, "users-inappm", False),
        (True, True, True, DEFAULT_FREE_PLAN, True),
        (True, False, False, DEFAULT_FREE_PLAN, True),
        (True, False, True, DEFAULT_FREE_PLAN, False),
        (True, False, False, "users-inappm", True),
        (True, False, True, "users-inappm", True),
    ],
)
def test_should_do_flake_detection(
    dbsession, mocker, config, feature_flag, private, plan, ex_result
):
    mock_all_plans_and_tiers()
    owner = OwnerFactory(plan=plan)
    repo = RepositoryFactory(private=private, owner=owner)
    dbsession.add(repo)
    dbsession.flush()

    mocked_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
    mocked_feature.check_value.return_value = feature_flag

    yaml = {"test_analytics": {"flake_detection": config}}

    result = should_do_flaky_detection(repo, UserYaml.from_dict(yaml))

    assert result == ex_result


def test_specific_error_message(mocker):
    mock_repo_service = mock.AsyncMock()
    mocker.patch(
        "helpers.notifier.get_repo_provider_service", return_value=mock_repo_service
    )
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.AsyncMock(),
    )

    upload = UploadFactory()
    error = UploadError(
        report_upload=upload,
        error_code="unsupported_file_format",
        error_params={
            "error_message": "Error parsing JUnit XML in test.xml at 4:32: ParserError: No name found"
        },
    )
    tn = TestResultsNotifier(CommitFactory(), None, error=error)
    result = tn.error_comment()
    expected = """### :x: Unsupported file format

> Upload processing failed due to unsupported file format. Please review the parser error message:
> `Error parsing JUnit XML in test.xml at 4:32: ParserError: No name found`
> For more help, visit our [troubleshooting guide](https://docs.codecov.com/docs/test-analytics#troubleshooting).
"""

    assert result == (True, "comment_posted")
    mock_repo_service.edit_comment.assert_called_with(
        tn._pull.database_pull.pullid, tn._pull.database_pull.commentid, expected
    )


def test_specific_error_message_no_error(mocker):
    mock_repo_service = mock.AsyncMock()
    mocker.patch(
        "helpers.notifier.get_repo_provider_service", return_value=mock_repo_service
    )
    mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=mock.AsyncMock(),
    )

    tn = TestResultsNotifier(CommitFactory(), None)
    result = tn.error_comment()
    expected = """:x: We are unable to process any of the uploaded JUnit XML files. Please ensure your files are in the right format."""

    assert result == (True, "comment_posted")
    mock_repo_service.edit_comment.assert_called_with(
        tn._pull.database_pull.pullid, tn._pull.database_pull.commentid, expected
    )
