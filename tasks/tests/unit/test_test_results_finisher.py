import datetime
from pathlib import Path

import pytest
from mock import AsyncMock, call
from shared.torngit.exceptions import TorngitClientError
from test_results_parser import Outcome

from database.enums import ReportType
from database.models import CommitReport, RepositoryFlag, Test, TestInstance
from database.tests.factories import CommitFactory, PullFactory, UploadFactory
from services.repository import EnrichedPull
from services.test_results import generate_test_id
from tasks.test_results_finisher import TestResultsFinisherTask

here = Path(__file__)


@pytest.fixture
def mock_metrics(mocker):
    mocked_metrics = mocker.patch(
        "tasks.test_results_finisher.metrics",
        mocker.MagicMock(),
    )
    return mocked_metrics


@pytest.fixture
def test_results_mock_app(mocker):
    mocked_app = mocker.patch.object(
        TestResultsFinisherTask,
        "app",
        tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
    )
    return mocked_app


@pytest.fixture
def mock_repo_provider_comments(mocker):
    m = mocker.MagicMock(
        edit_comment=AsyncMock(return_value=True),
        post_comment=AsyncMock(return_value={"id": 1}),
    )
    _ = mocker.patch(
        "services.test_results.get_repo_provider_service",
        return_value=m,
    )
    return m


@pytest.fixture
def test_results_setup(mocker, dbsession):
    mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

    commit = CommitFactory.create(
        message="hello world",
        commitid="cd76b0821854a780b60012aed85af0a8263004ad",
        repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
        repository__owner__username="joseph-sentry",
        repository__owner__service="github",
        repository__name="codecov-demo",
    )
    dbsession.add(commit)
    dbsession.flush()

    repoid = commit.repoid

    current_report_row = CommitReport(
        commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
    )
    dbsession.add(current_report_row)
    dbsession.flush()

    pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

    _ = mocker.patch(
        "services.test_results.fetch_and_update_pull_request_information_from_commit",
        return_value=EnrichedPull(
            database_pull=pull,
            provider_pull={},
        ),
    )

    uploads = [UploadFactory.create() for _ in range(4)]
    uploads[3].created_at += datetime.timedelta(0, 3)

    for upload in uploads:
        upload.report = current_report_row
        upload.report.commit.repoid = repoid
        dbsession.add(upload)
    dbsession.flush()

    flags = [RepositoryFlag(repository_id=repoid, flag_name=str(i)) for i in range(2)]
    for flag in flags:
        dbsession.add(flag)
    dbsession.flush()

    uploads[0].flags = [flags[0]]
    uploads[1].flags = [flags[1]]
    uploads[2].flags = []
    uploads[3].flags = [flags[0]]
    dbsession.flush()

    test_name = "test_name"
    test_suite = "test_testsuite"

    test_id1 = generate_test_id(repoid, test_name + "0", test_suite, "a")
    test1 = Test(
        id_=test_id1,
        repoid=repoid,
        name=test_name + "0",
        testsuite=test_suite,
        flags_hash="a",
    )
    dbsession.add(test1)

    test_id2 = generate_test_id(repoid, test_name + "1", test_suite, "b")
    test2 = Test(
        id_=test_id2,
        repoid=repoid,
        name=test_name + "1",
        testsuite=test_suite,
        flags_hash="b",
    )
    dbsession.add(test2)

    test_id3 = generate_test_id(repoid, test_name + "2", test_suite, "")
    test3 = Test(
        id_=test_id3,
        repoid=repoid,
        name=test_name + "2",
        testsuite=test_suite,
        flags_hash="",
    )
    dbsession.add(test3)

    test_id4 = generate_test_id(repoid, test_name + "3", test_suite, "")
    test4 = Test(
        id_=test_id4,
        repoid=repoid,
        name=test_name + "3",
        testsuite=test_suite,
        flags_hash="",
    )
    dbsession.add(test4)

    dbsession.flush()

    duration = 1
    test_instances = [
        TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="This should not be in the comment, it will get overwritten by the last test instance",
            duration_seconds=duration,
            upload_id=uploads[0].id,
        ),
        TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Failure),
            failure_message="Shared failure message",
            duration_seconds=duration,
            upload_id=uploads[1].id,
        ),
        TestInstance(
            test_id=test_id3,
            outcome=str(Outcome.Failure),
            failure_message="Shared failure message",
            duration_seconds=duration,
            upload_id=uploads[2].id,
        ),
        TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="<pre>Fourth \r\n\r\n</pre> | test  | instance |",
            duration_seconds=duration,
            upload_id=uploads[3].id,
        ),
        TestInstance(
            test_id=test_id4,
            outcome=str(Outcome.Failure),
            failure_message=None,
            duration_seconds=duration,
            upload_id=uploads[3].id,
        ),
    ]
    for instance in test_instances:
        dbsession.add(instance)
    dbsession.flush()

    return (repoid, commit, pull, test_instances)


class TestUploadTestFinisherTask(object):
    @pytest.mark.integration
    @pytest.mark.django_db(databases={"default"})
    def test_upload_finisher_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        mock_metrics,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        repoid, commit, pull, _ = test_results_setup

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {"notify_attempted": True, "notify_succeeded": True}

        assert expected_result == result
        mock_repo_provider_comments.post_comment.assert_called_with(
            pull.pullid,
            f"**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.\n\n### :x: Failed Test Results: \nCompleted 4 tests with **`4 failed`**, 0 passed and 0 skipped.\n<details><summary>View the full list of failed tests</summary>\n\n| **Test Description** | **Failure message** |\n| :-- | :-- |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name0<br>Envs:<br>- 0<br></pre> | <pre>&lt;pre&gt;Fourth <br><br>&lt;/pre&gt; | test  | instance |</pre> |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name1<br>Envs:<br>- 1<br></pre> | <pre>Shared failure message</pre> |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name2<br>Envs:<br>- default<br></pre> | <pre>Shared failure message</pre> |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name3<br>Envs:<br>- 0<br></pre> | <pre>No failure message available</pre> |",
        )

        mock_metrics.incr.assert_has_calls(
            [
                call(
                    "test_results.finisher",
                    tags={"status": "success", "reason": "tests_failed"},
                ),
                call(
                    "test_results.finisher.test_result_notifier",
                    tags={"status": True, "reason": "comment_posted"},
                ),
            ]
        )
        calls = [
            call("test_results.finisher.fetch_latest_test_instances"),
            call("test_results.finisher.notification"),
        ]
        for c in calls:
            assert c in mock_metrics.timing.mock_calls

    @pytest.mark.integration
    def test_upload_finisher_task_call_no_failures(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        mock_metrics,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        repoid, commit, _, test_instances = test_results_setup

        for instance in test_instances:
            instance.outcome = str(Outcome.Pass)
        dbsession.flush()

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {"notify_attempted": False, "notify_succeeded": False}
        test_results_mock_app.tasks[
            "app.tasks.notify.Notify"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "commitid": commit.commitid,
                "current_yaml": {"codecov": {"max_report_age": False}},
                "repoid": repoid,
            },
        )

        assert expected_result == result

        mock_metrics.incr.assert_has_calls(
            [
                call(
                    "test_results.finisher",
                    tags={
                        "status": "normal_notify_called",
                        "reason": "all_tests_passed",
                    },
                ),
            ]
        )
        calls = [
            call("test_results.finisher.fetch_latest_test_instances"),
        ]
        for c in calls:
            assert c in mock_metrics.timing.mock_calls

    @pytest.mark.integration
    def test_upload_finisher_task_call_no_success(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        mock_metrics,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        repoid, commit, _, _ = test_results_setup

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": False}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {"notify_attempted": False, "notify_succeeded": False}

        assert expected_result == result

        mock_metrics.incr.assert_has_calls(
            [
                call(
                    "test_results.finisher",
                    tags={"status": "failure", "reason": "no_successful_processing"},
                ),
            ]
        )
        assert mock_metrics.timing.mock_calls == []

    @pytest.mark.integration
    def test_upload_finisher_task_call_existing_comment(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        mock_metrics,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        repoid, commit, pull, _ = test_results_setup

        pull.commentid = 1
        dbsession.flush()

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {"notify_attempted": True, "notify_succeeded": True}

        mock_repo_provider_comments.edit_comment.assert_called_with(
            pull.pullid,
            1,
            "**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.\n\n### :x: Failed Test Results: \nCompleted 4 tests with **`4 failed`**, 0 passed and 0 skipped.\n<details><summary>View the full list of failed tests</summary>\n\n| **Test Description** | **Failure message** |\n| :-- | :-- |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name0<br>Envs:<br>- 0<br></pre> | <pre>&lt;pre&gt;Fourth <br><br>&lt;/pre&gt; | test  | instance |</pre> |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name1<br>Envs:<br>- 1<br></pre> | <pre>Shared failure message</pre> |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name2<br>Envs:<br>- default<br></pre> | <pre>Shared failure message</pre> |\n| <pre>Testsuite:<br>test_testsuite<br>Test name:<br>test_name3<br>Envs:<br>- 0<br></pre> | <pre>No failure message available</pre> |",
        )

        assert expected_result == result

    @pytest.mark.integration
    def test_upload_finisher_task_call_comment_fails(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        mock_metrics,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        repoid, commit, _, _ = test_results_setup

        mock_repo_provider_comments.post_comment.side_effect = TorngitClientError

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {"notify_attempted": True, "notify_succeeded": False}

        assert expected_result == result

        mock_metrics.incr.assert_has_calls(
            [
                call(
                    "test_results.finisher",
                    tags={"status": "success", "reason": "tests_failed"},
                ),
                call(
                    "test_results.finisher.test_result_notifier",
                    tags={"status": False, "reason": "torngit_error"},
                ),
            ]
        )
        calls = [
            call("test_results.finisher.fetch_latest_test_instances"),
            call("test_results.finisher.notification"),
        ]
        for c in calls:
            assert c in mock_metrics.timing.mock_calls
