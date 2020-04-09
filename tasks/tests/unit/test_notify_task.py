import pytest
from asyncio import Future

from covreports.reports.resources import Report
from celery.exceptions import Retry, MaxRetriesExceededError
from torngit.exceptions import TorngitClientError, TorngitServer5xxCodeError
from redis.exceptions import LockError

from helpers.exceptions import RepositoryWithoutValidBotError
from tasks.notify import NotifyTask
from services.decoration import Decoration
from services.notification.notifiers.base import NotificationResult
from services.notification import NotificationService
from database.tests.factories import (
    RepositoryFactory,
    CommitFactory,
    OwnerFactory,
    PullFactory,
)


class TestNotifyTaskHelpers(object):
    def test_fetch_parent(self, dbsession):
        task = NotifyTask()
        owner = OwnerFactory.create(
            unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            username="ThiagoCodecov",
        )
        repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}},
        )
        different_repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}},
        )
        dbsession.add(repository)
        right_parent_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=repository,
        )
        wrong_parent_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=different_repository,
        )
        another_wrong_parent_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="bf303450570d7a84f8c3cdedac5ac23e27a64c19",
            repository=repository,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            parent_commit_id="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=repository,
        )
        dbsession.add(commit)
        dbsession.add(another_wrong_parent_commit)
        dbsession.add(repository)
        dbsession.add(different_repository)
        dbsession.add(right_parent_commit)
        dbsession.add(wrong_parent_commit)
        dbsession.flush()
        assert task.fetch_parent(commit) == right_parent_commit


class TestNotifyTask(object):
    @pytest.mark.asyncio
    async def test_simple_call_no_notifications(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.io"
        mocker.patch.object(NotifyTask, "app")
        mocked_should_send_notifications = mocker.patch.object(
            NotifyTask, "should_send_notifications", return_value=False
        )
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        result = await task.run_async_within_lock(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml={}
        )
        assert result == {"notified": False, "notifications": None}
        mocked_should_send_notifications.assert_called_with(
            {}, commit, fetch_and_update_whether_ci_passed_result.result()
        )

    @pytest.mark.asyncio
    async def test_simple_call_no_notifications_no_yaml_given(
        self, dbsession, mocker, mock_storage, mock_configuration, mock_repo_provider
    ):
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.io"
        mocker.patch.object(NotifyTask, "app")
        mocked_should_send_notifications = mocker.patch.object(
            NotifyTask, "should_send_notifications", return_value=False
        )
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        mocked_fetch_yaml = mocker.patch(
            "services.yaml.fetch_commit_yaml_from_provider", return_value=Future()
        )
        mocked_fetch_yaml.return_value.set_result({})
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        result = await task.run_async_within_lock(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml=None
        )
        assert result == {"notified": False, "notifications": None}
        mocked_should_send_notifications.assert_called_with(
            {}, commit, fetch_and_update_whether_ci_passed_result.result()
        )
        mocked_fetch_yaml.assert_called_with(commit, mock_repo_provider)

    @pytest.mark.asyncio
    async def test_simple_call_yes_notifications_no_base(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        fake_notifier = mocker.MagicMock(
            notify=mocker.MagicMock(return_value=Future()),
            is_enabled=mocker.MagicMock(return_value=True),
            title="the_title",
        )
        fake_notifier.name = "fake_hahaha"
        fake_notifier.notify.return_value.set_result(
            NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation="",
                data_sent={"all": ["The", 1, "data"]},
            )
        )
        mocker.patch.object(
            NotificationService, "get_notifiers_instances", return_value=[fake_notifier]
        )
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.io"
        mocker.patch.object(NotifyTask, "app")
        mocker.patch.object(NotifyTask, "should_send_notifications", return_value=True)
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        mocked_fetch_pull = mocker.patch(
            "tasks.notify.fetch_and_update_pull_request_information_from_commit",
            return_value=Future(),
        )
        mocked_fetch_pull.return_value.set_result(None)
        commit = CommitFactory.create(message="", pullid=None,)
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        result = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={"coverage": {"status": {"patch": True}}},
        )
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "fake_hahaha",
                    "title": "the_title",
                    "result": {
                        "data_sent": {"all": ["The", 1, "data"]},
                        "notification_successful": True,
                        "notification_attempted": True,
                        "data_received": None,
                        "explanation": "",
                    },
                }
            ],
        }
        assert result["notifications"][0] == expected_result["notifications"][0]
        assert result["notifications"] == expected_result["notifications"]
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_simple_call_should_delay(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.io"
        mocker.patch.object(NotifyTask, "app")
        mocked_should_wait_longer = mocker.patch.object(
            NotifyTask, "should_wait_longer", return_value=True
        )
        mocked_retry = mocker.patch.object(NotifyTask, "retry", side_effect=Retry())
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        with pytest.raises(Retry):
            await task.run_async_within_lock(
                dbsession,
                repoid=commit.repoid,
                commitid=commit.commitid,
                current_yaml={},
            )
        mocked_retry.assert_called_with(countdown=15, max_retries=10)
        mocked_should_wait_longer.assert_called_with(
            {}, commit, fetch_and_update_whether_ci_passed_result.result()
        )

    @pytest.mark.asyncio
    async def test_simple_call_should_delay_using_integration(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.io"
        mocker.patch.object(NotifyTask, "app")
        mocked_should_wait_longer = mocker.patch.object(
            NotifyTask, "should_wait_longer", return_value=True
        )
        mocked_retry = mocker.patch.object(NotifyTask, "retry", side_effect=Retry())
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository__using_integration=True,
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        with pytest.raises(Retry):
            await task.run_async_within_lock(
                dbsession,
                repoid=commit.repoid,
                commitid=commit.commitid,
                current_yaml={},
            )
        mocked_retry.assert_called_with(countdown=180, max_retries=5)
        mocked_should_wait_longer.assert_called_with(
            {}, commit, fetch_and_update_whether_ci_passed_result.result()
        )

    @pytest.mark.asyncio
    async def test_simple_call_not_able_fetch_ci(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.io"
        mocker.patch.object(NotifyTask, "app")
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_exception(
            TorngitClientError(401, "response", "message")
        )
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository__using_integration=True,
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        res = await task.run_async_within_lock(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml={}
        )
        expected_result = {
            "notifications": None,
            "notified": False,
            "reason": "not_able_fetch_ci_result",
        }
        assert expected_result == res

    @pytest.mark.asyncio
    async def test_simple_call_not_able_fetch_ci_server_issues(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.io"
        mocker.patch.object(NotifyTask, "app")
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_exception(
            TorngitServer5xxCodeError()
        )
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository__using_integration=True,
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        res = await task.run_async_within_lock(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml={}
        )
        expected_result = {
            "notifications": None,
            "notified": False,
            "reason": "server_issues_ci_result",
        }
        assert expected_result == res

    def test_should_send_notifications_ci_did_not_pass(self, dbsession, mocker):
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository__using_integration=True,
        )
        mocked_app = mocker.patch.object(NotifyTask, "app")
        set_error_task_caller = mocker.MagicMock()
        mocked_app.tasks = {"app.tasks.status.SetError": set_error_task_caller}
        dbsession.add(commit)
        dbsession.flush()
        ci_passed = False
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        res = task.should_send_notifications(current_yaml, commit, ci_passed)
        assert not res
        set_error_task_caller.apply_async.assert_called_with(
            args=None,
            kwargs=dict(
                repoid=commit.repoid, commitid=commit.commitid, message="CI failed."
            ),
            queue="new_tasks",
        )

    @pytest.mark.asyncio
    async def test_notify_task_no_bot(self, dbsession, mocker):
        get_repo_provider_service = mocker.patch(
            "tasks.notify.get_repo_provider_service"
        )
        get_repo_provider_service.side_effect = RepositoryWithoutValidBotError()
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository__using_integration=True,
        )
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        res = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
        expected_result = {
            "notifications": None,
            "notified": False,
            "reason": "no_valid_bot",
        }
        assert expected_result == res

    @pytest.mark.asyncio
    async def test_submit_third_party_notifications_exception(self, mocker, dbsession):
        current_yaml = {}
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository, branch="new_branch")
        pull = PullFactory.create(
            repository=repository, base=base_commit.commitid, head=head_commit.commitid
        )
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        repository = base_commit.repository
        base_report = Report()
        head_report = Report()
        good_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mocker.MagicMock(return_value=Future()),
            title="good_notifier",
        )
        bad_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mocker.MagicMock(return_value=Future()),
            title="bad_notifier",
        )
        disabled_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=False), title="disabled_notifier"
        )
        good_notifier.notify.return_value.set_result(
            NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation="",
                data_sent={"some": "data"},
            )
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.return_value.set_exception(Exception("This is bad"))
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[bad_notifier, good_notifier, disabled_notifier],
        )
        task = NotifyTask()
        expected_result = [
            {"notifier": "bad_name", "title": "bad_notifier", "result": None},
            {
                "notifier": "good_name",
                "title": "good_notifier",
                "result": {
                    "notification_attempted": True,
                    "notification_successful": True,
                    "explanation": "",
                    "data_sent": {"some": "data"},
                    "data_received": None,
                },
            },
        ]
        res = await task.submit_third_party_notifications(
            current_yaml, base_commit, head_commit, base_report, head_report, pull, Decoration.standard
        )
        assert expected_result == res

    @pytest.mark.asyncio
    async def test_notify_task_max_retries_exceeded(
        self, dbsession, mocker, mock_repo_provider
    ):
        mocker.patch.object(NotifyTask, "should_wait_longer", return_value=True)
        mocker.patch.object(NotifyTask, "retry", side_effect=MaxRetriesExceededError())
        mocked_fetch_and_update_whether_ci_passed = mocker.patch.object(
            NotifyTask, "fetch_and_update_whether_ci_passed", return_value=Future()
        )
        mocked_fetch_and_update_whether_ci_passed.return_value.set_result(True)
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            repository__using_integration=True,
        )
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        res = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
        expected_result = {
            "notifications": None,
            "notified": False,
            "reason": "too_many_retries",
        }
        assert expected_result == res

    @pytest.mark.asyncio
    async def test_run_async_unobtainable_lock(self, dbsession, mock_redis, mocker):
        mocked_run_async_within_lock = mocker.patch.object(
            NotifyTask, "run_async_within_lock"
        )
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        mock_redis.lock.side_effect = LockError()
        mock_redis.get.return_value = None
        res = await task.run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
        assert res == {
            "notifications": None,
            "notified": False,
            "reason": "unobtainable_lock",
        }
        assert not mocked_run_async_within_lock.called

    @pytest.mark.asyncio
    async def test_run_async_other_jobs_coming(self, dbsession, mock_redis, mocker):
        mocked_run_async_within_lock = mocker.patch.object(
            NotifyTask, "run_async_within_lock"
        )
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        mock_redis.get.return_value = True
        res = await task.run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
        assert res == {
            "notifications": None,
            "notified": False,
            "reason": "has_other_notifies_coming",
        }
        assert not mocked_run_async_within_lock.called

    @pytest.mark.asyncio
    async def test_run_async_can_run_logic(self, dbsession, mock_redis, mocker):
        mocked_run_async_within_lock = mocker.patch.object(
            NotifyTask, "run_async_within_lock"
        )
        mocked_run_async_within_lock.return_value = Future()
        mocked_run_async_within_lock.return_value.set_result(
            {"notifications": [], "notified": True, "reason": "yay",}
        )
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        mock_redis.get.return_value = False
        res = await task.run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
        assert res == {
            "notifications": [],
            "notified": True,
            "reason": "yay",
        }
        mocked_run_async_within_lock.assert_called_with(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
