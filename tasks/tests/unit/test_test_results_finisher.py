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


class TestUploadTestFinisherTask(object):
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_finisher_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_app = mocker.patch.object(
            TestResultsFinisherTask,
            "app",
            tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
        )

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

        upload1 = UploadFactory.create()
        dbsession.add(upload1)
        dbsession.flush()

        upload2 = UploadFactory.create()
        upload2.created_at = upload1.created_at + datetime.timedelta(0, 3)
        dbsession.add(upload2)
        dbsession.flush()

        current_report_row = CommitReport(
            commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
        )
        dbsession.add(current_report_row)
        dbsession.flush()
        upload1.report = current_report_row
        upload2.report = current_report_row
        dbsession.flush()

        pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

        _ = mocker.patch(
            "services.test_results.fetch_and_update_pull_request_information_from_commit",
            return_value=EnrichedPull(
                database_pull=pull,
                provider_pull={},
            ),
        )
        mock_metrics = mocker.patch(
            "tasks.test_results_finisher.metrics",
            mocker.MagicMock(),
        )

        mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

        m = mocker.MagicMock(
            edit_comment=AsyncMock(return_value=True),
            post_comment=AsyncMock(return_value={"id": 1}),
        )
        mocked_repo_provider = mocker.patch(
            "services.test_results.get_repo_provider_service",
            return_value=m,
        )

        repoid = upload1.report.commit.repoid
        upload2.report.commit.repoid = repoid
        dbsession.flush()

        flag1 = RepositoryFlag(repository_id=repoid, flag_name="a")
        flag2 = RepositoryFlag(repository_id=repoid, flag_name="b")
        dbsession.flush()

        upload1.flags = [flag1]
        upload2.flags = [flag2]
        dbsession.flush()

        upload_id1 = upload1.id
        upload_id2 = upload2.id

        test_id1 = generate_test_id(repoid, "test_name", "test_testsuite", "a")
        test_id2 = generate_test_id(repoid, "test_name", "test_testsuite", "b")

        test1 = Test(
            id_=test_id1,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="a",
        )
        dbsession.add(test1)
        dbsession.flush()
        test2 = Test(
            id_=test_id2,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="b",
        )
        dbsession.add(test2)
        dbsession.flush()

        test_instance1 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="bad",
            duration_seconds=1,
            upload_id=upload_id1,
        )
        dbsession.add(test_instance1)
        dbsession.flush()

        test_instance2 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="<pre>not that bad</pre> | hello | goodbye |",
            duration_seconds=1,
            upload_id=upload_id2,
        )
        dbsession.add(test_instance2)
        dbsession.flush()

        test_instance3 = TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Failure),
            failure_message="okay i guess",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance3)
        dbsession.flush()

        test_instance4 = TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Failure),
            failure_message="<pre>not that\r\n\r\n bad</pre> | hello | goodbye |",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance4)
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
        m.post_comment.assert_called_with(
            pull.pullid,
            f"**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.\n\n### :x: Failed Test Results: \nCompleted 2 tests with **`2 failed`**, 0 passed and 0 skipped.\n<details><summary>View the full list of failed tests</summary>\n\n| **Test Description** | **Failure message** |\n| :-- | :-- |\n| <pre>Testsuite: test_testsuite<br>Test name: test_name<br>Envs: <br>- b</pre> | <pre>\\<pre\\>not that bad\\</pre\\> \\| hello \\| goodbye \\|</pre> |\n| <pre>Testsuite: test_testsuite<br>Test name: test_name<br>Envs: <br>- a</pre> | <pre>okay i guess</pre> |",
        )

        assert expected_result == result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_finisher_task_call_multi_env_fail(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_app = mocker.patch.object(
            TestResultsFinisherTask,
            "app",
            tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
        )

        mock_metrics = mocker.patch(
            "tasks.test_results_finisher.metrics",
            mocker.MagicMock(),
        )

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

        upload1 = UploadFactory.create()
        dbsession.add(upload1)
        dbsession.flush()

        upload2 = UploadFactory.create()
        upload2.created_at = upload1.created_at + datetime.timedelta(0, 3)
        dbsession.add(upload2)
        dbsession.flush()

        current_report_row = CommitReport(
            commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
        )
        dbsession.add(current_report_row)
        dbsession.flush()
        upload1.report = current_report_row
        upload2.report = current_report_row
        dbsession.flush()

        pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

        _ = mocker.patch(
            "services.test_results.fetch_and_update_pull_request_information_from_commit",
            return_value=EnrichedPull(
                database_pull=pull,
                provider_pull={},
            ),
        )

        mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

        m = mocker.MagicMock(
            edit_comment=AsyncMock(return_value=True),
            post_comment=AsyncMock(return_value={"id": 1}),
        )
        mocked_repo_provider = mocker.patch(
            "services.test_results.get_repo_provider_service",
            return_value=m,
        )

        repoid = upload1.report.commit.repoid
        upload2.report.commit.repoid = repoid
        dbsession.flush()

        flag1 = RepositoryFlag(repository_id=repoid, flag_name="a")
        flag2 = RepositoryFlag(repository_id=repoid, flag_name="b")
        dbsession.flush()

        upload1.flags = [flag1]
        upload2.flags = [flag2]
        dbsession.flush()

        upload_id1 = upload1.id
        upload_id2 = upload2.id

        test_id1 = generate_test_id(repoid, "test_name", "test_testsuite", "a")
        test_id2 = generate_test_id(repoid, "test_name", "test_testsuite", "b")
        test_id3 = generate_test_id(repoid, "test_name_2", "test_testsuite", "a")

        test1 = Test(
            id_=test_id1,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="a",
        )
        dbsession.add(test1)
        dbsession.flush()
        test2 = Test(
            id_=test_id2,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="b",
        )
        dbsession.add(test2)
        dbsession.flush()
        test3 = Test(
            id_=test_id3,
            repoid=repoid,
            name="test_name_2",
            testsuite="test_testsuite",
            flags_hash="a",
        )
        dbsession.add(test3)
        dbsession.flush()

        test_instance1 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="bad",
            duration_seconds=1,
            upload_id=upload_id1,
        )
        dbsession.add(test_instance1)
        dbsession.flush()

        test_instance2 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="not that bad",
            duration_seconds=1,
            upload_id=upload_id2,
        )
        dbsession.add(test_instance2)
        dbsession.flush()

        test_instance3 = TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Failure),
            failure_message="not that bad",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance3)
        dbsession.flush()

        test_instance4 = TestInstance(
            test_id=test_id3,
            outcome=str(Outcome.Failure),
            failure_message="not that bad",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance4)
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
        m.post_comment.assert_called_with(
            pull.pullid,
            f"**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.\n\n### :x: Failed Test Results: \nCompleted 3 tests with **`3 failed`**, 0 passed and 0 skipped.\n<details><summary>View the full list of failed tests</summary>\n\n| **Test Description** | **Failure message** |\n| :-- | :-- |\n| <pre>Testsuite: test_testsuite<br>Test name: test_name<br>Envs: <br>- a<br><br>- b<br>Testsuite: test_testsuite<br>Test name: test_name_2<br>Envs: <br>- a</pre> | <pre>not that bad</pre> |",
        )

        assert expected_result == result

        mock_metrics.incr.assert_has_calls(
            [
                call("test_results.finisher", tags={"status": "failures_exist"}),
                call(
                    "test_results.finisher",
                    tags={"status": True, "reason": "notified"},
                ),
            ]
        )
        calls = [
            call("test_results.finisher.fetch_latest_test_instances"),
            call("test_results.finisher.notification"),
        ]
        for c in calls:
            assert c in mock_metrics.timing.mock_calls

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_finisher_task_call_no_failures(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_app = mocker.patch.object(
            TestResultsFinisherTask,
            "app",
            tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
        )

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

        upload1 = UploadFactory.create()
        dbsession.add(upload1)
        dbsession.flush()

        upload2 = UploadFactory.create()
        upload2.created_at = upload2.created_at + datetime.timedelta(0, 3)
        dbsession.add(upload2)
        dbsession.flush()

        current_report_row = CommitReport(
            commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
        )
        dbsession.add(current_report_row)
        dbsession.flush()
        upload1.report = current_report_row
        upload2.report = current_report_row
        dbsession.flush()

        pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

        _ = mocker.patch(
            "services.test_results.fetch_and_update_pull_request_information_from_commit",
            return_value=EnrichedPull(
                database_pull=pull,
                provider_pull={},
            ),
        )

        mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

        m = mocker.MagicMock(
            edit_comment=AsyncMock(return_value=True),
            post_comment=AsyncMock(return_value={"id": 1}),
        )
        mocked_repo_provider = mocker.patch(
            "services.test_results.get_repo_provider_service",
            return_value=m,
        )
        mock_metrics = mocker.patch(
            "tasks.test_results_finisher.metrics",
            mocker.MagicMock(),
        )

        repoid = upload1.report.commit.repoid
        upload2.report.commit.repoid = repoid
        dbsession.flush()

        flag1 = RepositoryFlag(repository_id=repoid, flag_name="a")
        flag2 = RepositoryFlag(repository_id=repoid, flag_name="b")
        dbsession.flush()

        upload1.flags = [flag1]
        upload2.flags = [flag2]
        dbsession.flush()

        upload_id1 = upload1.id
        upload_id2 = upload2.id

        test_id1 = generate_test_id(repoid, "test_name", "test_testsuite", "a")
        test_id2 = generate_test_id(repoid, "test_name", "test_testsuite", "b")

        test1 = Test(
            id_=test_id1,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="a",
        )
        dbsession.add(test1)
        dbsession.flush()
        test2 = Test(
            id_=test_id2,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="b",
        )
        dbsession.add(test2)
        dbsession.flush()

        test_instance1 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Pass),
            failure_message="bad",
            duration_seconds=1,
            upload_id=upload_id1,
        )
        dbsession.add(test_instance1)
        dbsession.flush()

        test_instance2 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Pass),
            failure_message="not that bad",
            duration_seconds=1,
            upload_id=upload_id2,
        )
        dbsession.add(test_instance2)
        dbsession.flush()

        test_instance3 = TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Pass),
            failure_message="okay i guess",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance3)
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
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_called_with(
            args=None,
            kwargs={
                "commitid": commit.commitid,
                "current_yaml": {"codecov": {"max_report_age": False}},
                "repoid": commit.repoid,
            },
        )

        assert expected_result == result

        mock_metrics.incr.assert_has_calls(
            [
                call(
                    "test_results.finisher",
                    tags={"status": "success", "reason": "no_failures"},
                ),
            ]
        )
        calls = [
            call("test_results.finisher.fetch_latest_test_instances"),
        ]
        for c in calls:
            assert c in mock_metrics.timing.mock_calls

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_finisher_task_call_no_success(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_app = mocker.patch.object(
            TestResultsFinisherTask,
            "app",
            tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
        )

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

        upload1 = UploadFactory.create()
        dbsession.add(upload1)
        dbsession.flush()

        upload2 = UploadFactory.create()
        upload2.created_at = upload2.created_at + datetime.timedelta(0, 3)
        dbsession.add(upload2)
        dbsession.flush()

        current_report_row = CommitReport(
            commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
        )
        dbsession.add(current_report_row)
        dbsession.flush()
        upload1.report = current_report_row
        upload2.report = current_report_row
        dbsession.flush()

        pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

        _ = mocker.patch(
            "services.test_results.fetch_and_update_pull_request_information_from_commit",
            return_value=EnrichedPull(
                database_pull=pull,
                provider_pull={},
            ),
        )

        mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

        m = mocker.MagicMock(
            edit_comment=AsyncMock(return_value=True),
            post_comment=AsyncMock(return_value={"id": 1}),
        )
        mocked_repo_provider = mocker.patch(
            "services.test_results.get_repo_provider_service",
            return_value=m,
        )

        mock_metrics = mocker.patch(
            "tasks.test_results_finisher.metrics",
            mocker.MagicMock(),
        )

        repoid = upload1.report.commit.repoid
        upload2.report.commit.repoid = repoid
        dbsession.flush()

        flag1 = RepositoryFlag(repository_id=repoid, flag_name="a")
        flag2 = RepositoryFlag(repository_id=repoid, flag_name="b")
        dbsession.flush()

        upload1.flags = [flag1]
        upload2.flags = [flag2]
        dbsession.flush()

        upload_id1 = upload1.id
        upload_id2 = upload2.id

        test_id1 = generate_test_id(repoid, "test_name", "test_testsuite", "a")
        test_id2 = generate_test_id(repoid, "test_name", "test_testsuite", "b")

        test1 = Test(
            id_=test_id1,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="a",
        )
        dbsession.add(test1)
        dbsession.flush()
        test2 = Test(
            id_=test_id2,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="b",
        )
        dbsession.add(test2)
        dbsession.flush()

        test_instance1 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Pass),
            failure_message="bad",
            duration_seconds=1,
            upload_id=upload_id1,
        )
        dbsession.add(test_instance1)
        dbsession.flush()

        test_instance2 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Pass),
            failure_message="not that bad",
            duration_seconds=1,
            upload_id=upload_id2,
        )
        dbsession.add(test_instance2)
        dbsession.flush()

        test_instance3 = TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Pass),
            failure_message="okay i guess",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance3)
        dbsession.flush()

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
                    tags={"status": "failure", "reason": "no_success"},
                ),
            ]
        )
        assert mock_metrics.timing.mock_calls == []

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_finisher_task_call_existing_comment(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_app = mocker.patch.object(
            TestResultsFinisherTask,
            "app",
            tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
        )

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

        upload1 = UploadFactory.create()
        dbsession.add(upload1)
        dbsession.flush()

        upload2 = UploadFactory.create()
        upload2.created_at = upload1.created_at + datetime.timedelta(0, 3)
        dbsession.add(upload2)
        dbsession.flush()

        current_report_row = CommitReport(
            commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
        )
        dbsession.add(current_report_row)
        dbsession.flush()
        upload1.report = current_report_row
        upload2.report = current_report_row
        dbsession.flush()

        pull = PullFactory.create(
            repository=commit.repository, head=commit.commitid, commentid=1, pullid=1
        )

        _ = mocker.patch(
            "services.test_results.fetch_and_update_pull_request_information_from_commit",
            return_value=EnrichedPull(
                database_pull=pull,
                provider_pull={},
            ),
        )

        mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

        m = mocker.MagicMock(
            edit_comment=AsyncMock(return_value=True),
            post_comment=AsyncMock(return_value={"id": 1}),
        )
        mocked_repo_provider = mocker.patch(
            "services.test_results.get_repo_provider_service",
            return_value=m,
        )

        repoid = upload1.report.commit.repoid
        upload2.report.commit.repoid = repoid
        dbsession.flush()

        flag1 = RepositoryFlag(repository_id=repoid, flag_name="a")
        flag2 = RepositoryFlag(repository_id=repoid, flag_name="b")
        dbsession.flush()

        upload1.flags = [flag1]
        upload2.flags = [flag2]
        dbsession.flush()

        upload_id1 = upload1.id
        upload_id2 = upload2.id

        test_id1 = generate_test_id(repoid, "test_name", "test_testsuite", "a")
        test_id2 = generate_test_id(repoid, "test_name", "test_testsuite", "b")

        test1 = Test(
            id_=test_id1,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="a",
        )
        dbsession.add(test1)
        dbsession.flush()
        test2 = Test(
            id_=test_id2,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="b",
        )
        dbsession.add(test2)
        dbsession.flush()

        test_instance1 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="bad",
            duration_seconds=1,
            upload_id=upload_id1,
        )
        dbsession.add(test_instance1)
        dbsession.flush()

        test_instance2 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="not that bad",
            duration_seconds=1,
            upload_id=upload_id2,
        )
        dbsession.add(test_instance2)
        dbsession.flush()

        test_instance3 = TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Failure),
            failure_message="okay i guess",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance3)
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

        m.edit_comment.assert_called_with(
            pull.pullid,
            1,
            "**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.\n\n### :x: Failed Test Results: \nCompleted 2 tests with **`2 failed`**, 0 passed and 0 skipped.\n<details><summary>View the full list of failed tests</summary>\n\n| **Test Description** | **Failure message** |\n| :-- | :-- |\n| <pre>Testsuite: test_testsuite<br>Test name: test_name<br>Envs: <br>- b</pre> | <pre>not that bad</pre> |\n| <pre>Testsuite: test_testsuite<br>Test name: test_name<br>Envs: <br>- a</pre> | <pre>okay i guess</pre> |",
        )

        assert expected_result == result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_finisher_task_call_comment_fails(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_app = mocker.patch.object(
            TestResultsFinisherTask,
            "app",
            tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
        )

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

        upload1 = UploadFactory.create()
        dbsession.add(upload1)
        dbsession.flush()

        upload2 = UploadFactory.create()
        upload2.created_at = upload2.created_at + datetime.timedelta(0, 3)
        dbsession.add(upload2)
        dbsession.flush()

        current_report_row = CommitReport(
            commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
        )
        dbsession.add(current_report_row)
        dbsession.flush()
        upload1.report = current_report_row
        upload2.report = current_report_row
        dbsession.flush()

        pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

        _ = mocker.patch(
            "services.test_results.fetch_and_update_pull_request_information_from_commit",
            return_value=EnrichedPull(
                database_pull=pull,
                provider_pull={},
            ),
        )

        mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

        m = mocker.MagicMock(
            edit_comment=AsyncMock(return_value=True),
            post_comment=AsyncMock(side_effect=TorngitClientError),
        )

        mocked_repo_provider = mocker.patch(
            "services.test_results.get_repo_provider_service",
            return_value=m,
        )

        mock_metrics = mocker.patch(
            "tasks.test_results_finisher.metrics",
            mocker.MagicMock(),
        )

        repoid = upload1.report.commit.repoid
        upload2.report.commit.repoid = repoid
        dbsession.flush()

        flag1 = RepositoryFlag(repository_id=repoid, flag_name="a")
        flag2 = RepositoryFlag(repository_id=repoid, flag_name="b")
        dbsession.flush()

        upload1.flags = [flag1]
        upload2.flags = [flag2]
        dbsession.flush()

        upload_id1 = upload1.id
        upload_id2 = upload2.id

        test_id1 = generate_test_id(repoid, "test_name", "test_testsuite", "a")
        test_id2 = generate_test_id(repoid, "test_name", "test_testsuite", "b")

        test1 = Test(
            id_=test_id1,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="a",
        )
        dbsession.add(test1)
        dbsession.flush()
        test2 = Test(
            id_=test_id2,
            repoid=repoid,
            name="test_name",
            testsuite="test_testsuite",
            flags_hash="b",
        )
        dbsession.add(test2)
        dbsession.flush()

        test_instance1 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="bad",
            duration_seconds=1,
            upload_id=upload_id1,
        )
        dbsession.add(test_instance1)
        dbsession.flush()

        test_instance2 = TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="not that bad",
            duration_seconds=1,
            upload_id=upload_id2,
        )
        dbsession.add(test_instance2)
        dbsession.flush()

        test_instance3 = TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Failure),
            failure_message="okay i guess",
            duration_seconds=2,
            upload_id=upload_id1,
        )

        dbsession.add(test_instance3)
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

        expected_result = {"notify_attempted": True, "notify_succeeded": False}

        assert expected_result == result

        mock_metrics.incr.assert_has_calls(
            [
                call("test_results.finisher", tags={"status": "failures_exist"}),
                call(
                    "test_results.finisher",
                    tags={"status": False, "reason": "notified"},
                ),
            ]
        )
        calls = [
            call("test_results.finisher.fetch_latest_test_instances"),
            call("test_results.finisher.notification"),
        ]
        for c in calls:
            assert c in mock_metrics.timing.mock_calls
