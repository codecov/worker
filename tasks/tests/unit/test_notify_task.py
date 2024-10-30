import json
from typing import Any
from unittest.mock import MagicMock, call

import httpx
import pytest
import respx
from celery.exceptions import MaxRetriesExceededError, Retry
from freezegun import freeze_time
from shared.celery_config import (
    activate_account_user_task_name,
    new_user_activated_task_name,
)
from shared.reports.resources import Report
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import (
    TorngitClientGeneralError,
    TorngitServer5xxCodeError,
)
from shared.torngit.gitlab import Gitlab
from shared.typings.oauth_token_types import Token
from shared.typings.torngit import GithubInstallationInfo, TorngitInstanceData
from shared.yaml import UserYaml

from database.enums import Decoration, Notification, NotificationState
from database.models.core import CommitNotification, GithubAppInstallation
from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from database.tests.factories.core import ReportFactory, UploadFactory
from helpers.checkpoint_logger import CheckpointLogger, _kwargs_key
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from services.decoration import DecorationDetails
from services.lock_manager import LockRetry
from services.notification import NotificationService
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)
from services.report import ReportService
from services.repository import EnrichedPull
from tasks.notify import (
    NotifyTask,
    _possibly_pin_commit_to_github_app,
    _possibly_refresh_previous_selection,
)


def _create_checkpoint_logger(mocker):
    mocker.patch(
        "helpers.checkpoint_logger._get_milli_timestamp",
        side_effect=[1337, 9001, 10000, 15000, 20000, 25000],
    )
    checkpoints = CheckpointLogger(UploadFlow)
    checkpoints.log(UploadFlow.UPLOAD_TASK_BEGIN)
    checkpoints.log(UploadFlow.PROCESSING_BEGIN)
    checkpoints.log(UploadFlow.INITIAL_PROCESSING_COMPLETE)
    checkpoints.log(UploadFlow.BATCH_PROCESSING_COMPLETE)
    checkpoints.log(UploadFlow.PROCESSING_COMPLETE)
    return checkpoints


@pytest.fixture
def enriched_pull(dbsession):
    repository = RepositoryFactory.create(
        owner__username="codecov",
        owner__unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        owner__plan="users-pr-inappm",
        name="example-python",
        image_token="abcdefghij",
        private=True,
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository)
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        state="merged",
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    provider_pull = {
        "author": {"id": "7123", "username": "tomcat"},
        "base": {
            "branch": "master",
            "commitid": "b92edba44fdd29fcc506317cc3ddeae1a723dd08",
        },
        "head": {
            "branch": "reason/some-testing",
            "commitid": "a06aef4356ca35b34c5486269585288489e578db",
        },
        "number": "1",
        "id": "1",
        "state": "open",
        "title": "Creating new code for reasons no one knows",
    }
    return EnrichedPull(database_pull=pull, provider_pull=provider_pull)


class TestNotifyTaskHelpers(object):
    def test_fetch_parent(self, dbsession):
        task = NotifyTask()
        owner = OwnerFactory.create(
            unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            username="ThiagoCodecov",
        )
        repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
        )
        different_repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
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

    def test_determine_decoration_type_from_pull_does_not_attempt_activation(
        self, dbsession, mocker, enriched_pull
    ):
        mock_activate_user = mocker.patch("tasks.notify.activate_user")
        decoration_details = DecorationDetails(
            decoration_type=Decoration.standard,
            reason="Auto activate not needed",
            should_attempt_author_auto_activation=False,
        )
        mock_determine_decoration_details = mocker.patch(
            "tasks.notify.determine_decoration_details", return_value=decoration_details
        )
        task = NotifyTask()
        res = task.determine_decoration_type_from_pull(enriched_pull)
        assert res == Decoration.standard
        mock_determine_decoration_details.assert_called_with(enriched_pull, None)
        assert not mock_activate_user.called

    def test_determine_decoration_type_from_pull_auto_activation_fails(
        self, dbsession, mocker, enriched_pull, with_sql_functions
    ):
        pr_author = OwnerFactory.create(
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()
        mock_activate_user = mocker.patch(
            "tasks.notify.activate_user", return_value=False
        )
        mock_schedule_new_user_activated_task = mocker.patch(
            "tasks.notify.NotifyTask.schedule_new_user_activated_task"
        )
        decoration_details = DecorationDetails(
            decoration_type=Decoration.upgrade,
            reason="User must be activated",
            should_attempt_author_auto_activation=True,
            activation_org_ownerid=enriched_pull.database_pull.repository.owner.ownerid,
            activation_author_ownerid=pr_author.ownerid,
        )
        mock_determine_decoration_details = mocker.patch(
            "tasks.notify.determine_decoration_details", return_value=decoration_details
        )
        task = NotifyTask()
        res = task.determine_decoration_type_from_pull(enriched_pull)
        assert res == Decoration.upgrade
        mock_determine_decoration_details.assert_called_with(enriched_pull, None)
        mock_activate_user.assert_called_with(
            dbsession,
            enriched_pull.database_pull.repository.owner.ownerid,
            pr_author.ownerid,
        )
        assert not mock_schedule_new_user_activated_task.called

    def test_determine_decoration_type_from_pull_attempt_activation(
        self, dbsession, mocker, enriched_pull, with_sql_functions
    ):
        pr_author = OwnerFactory.create(
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()
        mock_activate_user = mocker.patch(
            "tasks.notify.activate_user", return_value=True
        )
        decoration_details = DecorationDetails(
            decoration_type=Decoration.upgrade,
            reason="User must be activated",
            should_attempt_author_auto_activation=True,
            activation_org_ownerid=enriched_pull.database_pull.repository.owner.ownerid,
            activation_author_ownerid=pr_author.ownerid,
        )
        mock_determine_decoration_details = mocker.patch(
            "tasks.notify.determine_decoration_details", return_value=decoration_details
        )
        mocked_send_task = mocker.patch(
            "tasks.notify.celery_app.send_task", return_value=None
        )
        task = NotifyTask()
        res = task.determine_decoration_type_from_pull(enriched_pull)
        assert res == Decoration.standard
        mock_determine_decoration_details.assert_called_with(enriched_pull, None)
        mock_activate_user.assert_called_with(
            dbsession,
            enriched_pull.database_pull.repository.owner.ownerid,
            pr_author.ownerid,
        )
        assert mocked_send_task.call_count == 2

        new_user_activation_call = mocked_send_task.call_args_list[0]
        account_user_activation_call = mocked_send_task.call_args_list[1]
        assert new_user_activation_call == call(
            new_user_activated_task_name,
            args=None,
            kwargs=dict(
                org_ownerid=enriched_pull.database_pull.repository.owner.ownerid,
                user_ownerid=pr_author.ownerid,
            ),
        )
        assert account_user_activation_call[0] == (
            activate_account_user_task_name,
            None,
            {
                "org_ownerid": enriched_pull.database_pull.repository.owner.ownerid,
                "user_ownerid": pr_author.ownerid,
            },
        )

    @pytest.mark.parametrize("cached_id, app_to_save", [("24", "24"), (None, 12)])
    def test__possibly_refresh_previous_selection(
        self, cached_id, app_to_save, mocker, dbsession
    ):
        commit = CommitFactory(repository__owner__service="github")
        app = GithubAppInstallation(id_=12, owner=commit.repository.owner)
        other_app = GithubAppInstallation(id_=24, owner=commit.repository.owner)
        commit_notifications = [
            CommitNotification(
                commit=commit,
                notification_type=Notification.checks_project,
                state=NotificationState.success,
            ),
            CommitNotification(
                commit=commit,
                notification_type=Notification.checks_patch,
                state=NotificationState.error,
                gh_app_id=other_app.id,
            ),
            CommitNotification(
                commit=commit,
                notification_type=Notification.checks_changes,
                state=NotificationState.success,
                gh_app_id=app.id,
            ),
        ]
        dbsession.add_all([commit, app, other_app] + commit_notifications)
        dbsession.flush()
        mock_set_gh_app_for_commit = mocker.patch(
            "tasks.notify.set_github_app_for_commit"
        )
        mocker.patch("tasks.notify.get_github_app_for_commit", return_value=cached_id)
        assert _possibly_refresh_previous_selection(commit) == True
        mock_set_gh_app_for_commit.assert_called_with(app_to_save, commit)

    def test__possibly_refresh_previous_selection_false(self, mocker, dbsession):
        commit = CommitFactory(repository__owner__service="github")
        dbsession.add(commit)
        dbsession.flush()
        mocker.patch("tasks.notify.get_github_app_for_commit", return_value=None)
        mock_set_gh_app_for_commit = mocker.patch(
            "tasks.notify.set_github_app_for_commit"
        )
        assert _possibly_refresh_previous_selection(commit) == False
        mock_set_gh_app_for_commit.assert_not_called()

    def test_possibly_pin_commit_to_github_app_not_github_or_no_installation(
        self, mocker, dbsession
    ):
        commit = CommitFactory(repository__owner__service="gitlab")
        commit_from_gh = CommitFactory(repository__owner__service="github")
        dbsession.add_all([commit, commit_from_gh])
        dbsession.flush()
        mock_refresh_selection = mocker.patch(
            "tasks.notify._possibly_refresh_previous_selection", return_value=None
        )
        torngit = MagicMock(data=TorngitInstanceData())
        torngit_with_installation = MagicMock(
            data=TorngitInstanceData(installation=GithubInstallationInfo(id=12))
        )
        assert (
            _possibly_pin_commit_to_github_app(commit, torngit_with_installation)
            is None
        )
        mock_refresh_selection.assert_not_called()
        assert _possibly_pin_commit_to_github_app(commit_from_gh, torngit) is None
        mock_refresh_selection.assert_called_with(commit_from_gh)

    def test_possibly_pin_commit_to_github_app_new_selection(self, mocker, dbsession):
        commit = CommitFactory(repository__owner__service="github")
        dbsession.add(commit)
        dbsession.flush()
        mock_refresh_selection = mocker.patch(
            "tasks.notify._possibly_refresh_previous_selection", return_value=None
        )
        mock_set_gh_app_for_commit = mocker.patch(
            "tasks.notify.set_github_app_for_commit"
        )
        torngit = MagicMock(
            data=TorngitInstanceData(installation=GithubInstallationInfo(id=12))
        )
        assert _possibly_pin_commit_to_github_app(commit, torngit) == 12
        mock_refresh_selection.assert_called_with(commit)
        mock_set_gh_app_for_commit.assert_called_with(12, commit)

    def test_get_gitlab_extra_shas(self, dbsession):
        commit = CommitFactory(
            repository__owner__service="gitlab", repository__service_id=1000
        )
        dbsession.add(commit)
        report = ReportFactory(commit=commit)
        dbsession.add(report)
        uploads = [UploadFactory(report=report, job_code=i) for i in range(3)]
        dbsession.add_all(uploads)
        dbsession.flush()
        assert len(commit.report.uploads) == 3
        with respx.mock:
            respx.get("https://gitlab.com/api/v4/projects/1000/jobs/0").mock(
                return_value=httpx.Response(
                    status_code=200,
                    json={
                        "pipeline": {
                            "id": 0,
                            "project_id": 1000,
                            "sha": commit.commitid,
                        }
                    },
                )
            )
            respx.get("https://gitlab.com/api/v4/projects/1000/jobs/1").mock(
                return_value=httpx.Response(
                    status_code=200,
                    json={
                        "pipeline": {
                            "id": 1,
                            "project_id": 1000,
                            "sha": "508c25daba5bbc77d8e7cf3c1917d5859153cfd3",
                        }
                    },
                )
            )
            respx.get("https://gitlab.com/api/v4/projects/1000/jobs/2").mock(
                return_value=httpx.Response(status_code=400, json={})
            )
            repository_service = Gitlab(token={"key": "some_token"})
            task = NotifyTask()
            assert task.get_gitlab_extra_shas_to_notify(commit, repository_service) == {
                "508c25daba5bbc77d8e7cf3c1917d5859153cfd3",
            }


class TestNotifyTask(object):
    def test_simple_call_no_notifications(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocked_should_send_notifications = mocker.patch.object(
            NotifyTask, "should_send_notifications", return_value=False
        )
        fetch_and_update_whether_ci_passed_result = {}
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
        result = task.run_impl_within_lock(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml={}
        )
        assert result == {"notified": False, "notifications": None}
        mocked_should_send_notifications.assert_called_with(
            UserYaml({}), commit, fetch_and_update_whether_ci_passed_result, None
        )

    def test_simple_call_no_notifications_no_yaml_given(
        self, dbsession, mocker, mock_storage, mock_configuration, mock_repo_provider
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocked_should_send_notifications = mocker.patch.object(
            NotifyTask, "should_send_notifications", return_value=False
        )
        fetch_and_update_whether_ci_passed_result = {}
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
            "services.yaml.fetch_commit_yaml_from_provider"
        )
        mocked_fetch_yaml.return_value = {}
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        result = task.run_impl_within_lock(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml=None
        )
        assert result == {"notified": False, "notifications": None}
        mocked_should_send_notifications.assert_called_with(
            UserYaml({}), commit, fetch_and_update_whether_ci_passed_result, None
        )
        mocked_fetch_yaml.assert_called_with(commit, mock_repo_provider)

    def test_simple_call_no_notifications_commit_differs_from_pulls_head(
        self,
        dbsession,
        mocker,
        mock_storage,
        mock_configuration,
        mock_repo_provider,
        enriched_pull,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocked_should_send_notifications = mocker.patch.object(
            NotifyTask, "should_send_notifications", return_value=True
        )
        fetch_and_update_whether_ci_passed_result = {}
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        mocked_fetch_pull = mocker.patch(
            "tasks.notify.fetch_and_update_pull_request_information_from_commit"
        )
        head_report = Report()
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=head_report
        )
        mocked_fetch_pull.return_value = enriched_pull
        # commit different from provider pull recent head
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        result = task.run_impl_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={"codecov": {"notify": {"manual_trigger": True}}},
        )
        assert result == {
            "notified": False,
            "notifications": None,
            "reason": "User doesnt want notifications warning them that current head differs from pull request most recent head.",
        }
        mocked_should_send_notifications.assert_called_with(
            UserYaml({"codecov": {"notify": {"manual_trigger": True}}}),
            commit,
            fetch_and_update_whether_ci_passed_result,
            head_report,
        )

    def test_simple_call_yes_notifications_no_base(
        self,
        dbsession,
        mocker,
        mock_storage,
        mock_configuration,
        mock_checkpoint_submit,
    ):
        fake_notifier = mocker.MagicMock(
            AbstractBaseNotifier,
            is_enabled=mocker.MagicMock(return_value=True),
            title="the_title",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        fake_notifier.name = "fake_hahaha"
        fake_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"all": ["The", 1, "data"]},
        )
        mocker.patch.object(
            NotificationService, "get_notifiers_instances", return_value=[fake_notifier]
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocker.patch.object(NotifyTask, "save_patch_totals")
        mocker.patch.object(NotifyTask, "should_send_notifications", return_value=True)
        fetch_and_update_whether_ci_passed_result = {}
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        mocked_fetch_pull = mocker.patch(
            "tasks.notify.fetch_and_update_pull_request_information_from_commit"
        )
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=Report()
        )
        mocked_fetch_pull.return_value = None
        commit = CommitFactory.create(
            message="", pullid=None, repository__owner__service="github"
        )
        dbsession.add(commit)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        kwargs = {_kwargs_key(UploadFlow): checkpoints.data}

        task = NotifyTask()
        result = task.run_impl_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={"coverage": {"status": {"patch": True}}},
            **kwargs,
        )
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "fake_hahaha",
                    "title": "the_title",
                    "result": NotificationResult(
                        data_sent={"all": ["The", 1, "data"]},
                        notification_successful=True,
                        notification_attempted=True,
                        data_received=None,
                        explanation="",
                    ),
                }
            ],
        }
        assert result["notifications"] == expected_result["notifications"]
        assert result["notifications"][0] == expected_result["notifications"][0]
        assert result["notifications"] == expected_result["notifications"]
        assert result == expected_result
        dbsession.flush()
        dbsession.refresh(commit)
        assert commit.notified is True

        calls = [
            call(
                "notification_latency",
                UploadFlow.UPLOAD_TASK_BEGIN,
                UploadFlow.NOTIFIED,
            ),
        ]
        mock_checkpoint_submit.assert_has_calls(calls)

    def test_simple_call_no_pullrequest_found(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mocked_submit_third_party_notifications = mocker.patch.object(
            NotifyTask, "submit_third_party_notifications"
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocker.patch.object(NotifyTask, "should_send_notifications", return_value=True)
        fetch_and_update_whether_ci_passed_result = {}
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        mocked_fetch_pull = mocker.patch(
            "tasks.notify.fetch_and_update_pull_request_information_from_commit"
        )
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=Report()
        )
        mocked_fetch_pull.return_value = EnrichedPull(None, None)
        commit = CommitFactory.create(message="", pullid=None)
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        result = task.run_impl_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={"coverage": {"status": {"patch": True}}},
        )
        assert result == {
            "notified": True,
            "notifications": mocked_submit_third_party_notifications.return_value,
        }
        dbsession.flush()
        dbsession.refresh(commit)
        assert commit.notified is True

    def test_simple_call_should_delay(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocked_should_wait_longer = mocker.patch.object(
            NotifyTask, "should_wait_longer", return_value=True
        )
        mocked_retry = mocker.patch.object(NotifyTask, "retry", side_effect=Retry())
        fetch_and_update_whether_ci_passed_result = {}
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
            task.run_impl_within_lock(
                dbsession,
                repoid=commit.repoid,
                commitid=commit.commitid,
                current_yaml={},
            )
        mocked_retry.assert_called_with(countdown=15, max_retries=10)
        mocked_should_wait_longer.assert_called_with(
            UserYaml({}), commit, fetch_and_update_whether_ci_passed_result
        )

    def test_simple_call_should_delay_using_integration(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocked_should_wait_longer = mocker.patch.object(
            NotifyTask, "should_wait_longer", return_value=True
        )
        mocked_retry = mocker.patch.object(NotifyTask, "retry", side_effect=Retry())
        fetch_and_update_whether_ci_passed_result = {}
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
            task.run_impl_within_lock(
                dbsession,
                repoid=commit.repoid,
                commitid=commit.commitid,
                current_yaml={},
            )
        mocked_retry.assert_called_with(countdown=180, max_retries=5)
        mocked_should_wait_longer.assert_called_with(
            UserYaml({}), commit, fetch_and_update_whether_ci_passed_result
        )

    def test_simple_call_not_able_fetch_ci(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            side_effect=TorngitClientGeneralError(401, "response", "message"),
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
        res = task.run_impl_within_lock(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml={}
        )
        expected_result = {
            "notifications": None,
            "notified": False,
            "reason": "not_able_fetch_ci_result",
        }
        assert expected_result == res

    def test_simple_call_not_able_fetch_ci_server_issues(
        self, dbsession, mocker, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch.object(NotifyTask, "app")
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            side_effect=TorngitServer5xxCodeError(),
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
        res = task.run_impl_within_lock(
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
        mock_report = mocker.MagicMock(sessions=[mocker.MagicMock()])  # 1 session
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        res = task.should_send_notifications(
            current_yaml, commit, ci_passed, mock_report
        )
        assert not res
        set_error_task_caller.apply_async.assert_called_with(
            args=None,
            kwargs=dict(
                repoid=commit.repoid, commitid=commit.commitid, message="CI failed."
            ),
        )

    def test_should_send_notifications_after_n_builds(self, dbsession, mocker):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()

        mock_report = mocker.MagicMock(sessions=[mocker.MagicMock()])  # 1 session

        task = NotifyTask()
        current_yaml = {"codecov": {"notify": {"after_n_builds": 2}}}
        res = task.should_send_notifications(current_yaml, commit, True, mock_report)
        assert not res

    def test_notify_task_no_bot(self, dbsession, mocker):
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
        res = task.run_impl_within_lock(
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

    @freeze_time("2024-04-22T11:15:00")
    def test_notify_task_no_ghapp_available_one_rate_limited(self, dbsession, mocker):
        get_repo_provider_service = mocker.patch(
            "tasks.notify.get_repo_provider_service"
        )
        mock_retry = mocker.patch.object(NotifyTask, "retry", return_value=None)
        get_repo_provider_service.side_effect = NoConfiguredAppsAvailable(
            apps_count=2, rate_limited_count=1, suspended_count=1
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
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        res = task.run_impl_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
        assert res is None
        mock_retry.assert_called_with(max_retries=10, countdown=45 * 60)

    @freeze_time("2024-04-22T11:15:00")
    def test_notify_task_no_ghapp_available_all_suspended(self, dbsession, mocker):
        get_repo_provider_service = mocker.patch(
            "tasks.notify.get_repo_provider_service"
        )
        mock_retry = mocker.patch.object(NotifyTask, "retry", return_value=None)
        get_repo_provider_service.side_effect = NoConfiguredAppsAvailable(
            apps_count=1, rate_limited_count=0, suspended_count=1
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
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        res = task.run_impl_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
        )
        assert res == {
            "notified": False,
            "notifications": None,
            "reason": "no_valid_github_app_found",
        }
        mock_retry.assert_not_called()

    def test_submit_third_party_notifications_exception(self, mocker, dbsession):
        current_yaml = {}
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository, branch="new_branch")
        pull = PullFactory.create(
            repository=repository, base=base_commit.commitid, head=head_commit.commitid
        )
        enrichedPull = EnrichedPull(database_pull=pull, provider_pull={})
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        repository = base_commit.repository
        base_report = Report()
        head_report = Report()
        good_notifier = mocker.MagicMock(
            AbstractBaseNotifier,
            is_enabled=mocker.MagicMock(return_value=True),
            title="good_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        bad_notifier = mocker.MagicMock(
            AbstractBaseNotifier,
            is_enabled=mocker.MagicMock(return_value=True),
            title="bad_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        disabled_notifier = mocker.MagicMock(
            AbstractBaseNotifier,
            is_enabled=mocker.MagicMock(return_value=False),
            title="disabled_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        good_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"some": "data"},
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.side_effect = Exception("This is bad")
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[bad_notifier, good_notifier, disabled_notifier],
        )
        mocker.patch.object(NotifyTask, "save_patch_totals")
        task = NotifyTask()
        expected_result = [
            {"notifier": "bad_name", "title": "bad_notifier", "result": None},
            {
                "notifier": "good_name",
                "title": "good_notifier",
                "result": NotificationResult(
                    notification_attempted=True,
                    notification_successful=True,
                    explanation="",
                    data_sent={"some": "data"},
                    data_received=None,
                ),
            },
        ]
        res = task.submit_third_party_notifications(
            current_yaml,
            base_commit,
            head_commit,
            base_report,
            head_report,
            enrichedPull,
            mocker.MagicMock(),
        )
        assert expected_result == res

    def test_notify_task_max_retries_exceeded(
        self, dbsession, mocker, mock_repo_provider
    ):
        mocker.patch.object(NotifyTask, "should_wait_longer", return_value=True)
        mocker.patch.object(NotifyTask, "retry", side_effect=MaxRetriesExceededError())
        mocked_fetch_and_update_whether_ci_passed = mocker.patch.object(
            NotifyTask, "fetch_and_update_whether_ci_passed"
        )
        mocked_fetch_and_update_whether_ci_passed.return_value = True
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
        res = task.run_impl_within_lock(
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

    def test_run_impl_unobtainable_lock(self, dbsession, mock_redis, mocker):
        mocked_run_impl_within_lock = mocker.patch.object(
            NotifyTask, "run_impl_within_lock"
        )
        mocked_has_upcoming_notifies_according_to_redis = mocker.patch.object(
            NotifyTask, "has_upcoming_notifies_according_to_redis", return_value=False
        )
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        m = mocker.MagicMock()
        m.return_value.locked.return_value.__enter__.side_effect = LockRetry(60)
        mocker.patch("tasks.notify.LockManager", m)

        res = task.run_impl(
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
        assert not mocked_run_impl_within_lock.called

    def test_run_impl_other_jobs_coming(self, dbsession, mock_redis, mocker):
        mocked_run_impl_within_lock = mocker.patch.object(
            NotifyTask, "run_impl_within_lock"
        )
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        mock_redis.get.return_value = True
        res = task.run_impl(
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
        assert not mocked_run_impl_within_lock.called

    def test_run_impl_can_run_logic(self, dbsession, mock_redis, mocker):
        mocked_run_impl_within_lock = mocker.patch.object(
            NotifyTask, "run_impl_within_lock"
        )
        mocked_run_impl_within_lock.return_value = {
            "notifications": [],
            "notified": True,
            "reason": "yay",
        }
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_yaml = {"codecov": {"require_ci_to_pass": True}}
        task = NotifyTask()
        mock_redis.get.return_value = False
        checkpoints = _create_checkpoint_logger(mocker)
        checkpoints_data = json.loads(json.dumps(checkpoints.data))
        kwargs = {_kwargs_key(UploadFlow): checkpoints_data}
        res = task.run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
            **kwargs,
        )
        assert res == {"notifications": [], "notified": True, "reason": "yay"}
        kwargs = {_kwargs_key(UploadFlow): mocker.ANY}
        mocked_run_impl_within_lock.assert_called_with(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml=current_yaml,
            empty_upload=None,
            **kwargs,
        )

    def test_checkpoints_not_logged_outside_upload_flow(
        self, dbsession, mock_redis, mocker, mock_checkpoint_submit, mock_configuration
    ):
        fake_notifier = mocker.MagicMock(
            AbstractBaseNotifier,
            is_enabled=mocker.MagicMock(return_value=True),
            title="the_title",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        fake_notifier.name = "fake_hahaha"
        fake_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"all": ["The", 1, "data"]},
        )
        mocker.patch.object(
            NotificationService, "get_notifiers_instances", return_value=[fake_notifier]
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.io"
        )
        mocker.patch("tasks.notify.get_repo_provider_service_for_specific_commit")
        mocker.patch.object(NotifyTask, "app")
        mocker.patch.object(NotifyTask, "save_patch_totals")
        mocker.patch.object(NotifyTask, "should_send_notifications", return_value=True)
        fetch_and_update_whether_ci_passed_result = {}
        mocker.patch.object(
            NotifyTask,
            "fetch_and_update_whether_ci_passed",
            return_value=fetch_and_update_whether_ci_passed_result,
        )
        mocked_fetch_pull = mocker.patch(
            "tasks.notify.fetch_and_update_pull_request_information_from_commit"
        )
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=Report()
        )
        mocked_fetch_pull.return_value = None
        commit = CommitFactory.create(message="", pullid=None)
        dbsession.add(commit)
        dbsession.flush()

        task = NotifyTask()
        result = task.run_impl_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={"coverage": {"status": {"patch": True}}},
        )
        assert not mock_checkpoint_submit.called

    @pytest.mark.parametrize(
        "service,data,bot_token,expected_response",
        [
            pytest.param(
                "github",
                {},
                Token(username="test-codecov-commenter-bot"),
                True,
                id="expected_to_be_true",
            ),
            pytest.param(
                "bitbucket",
                {},
                Token(username="test-codecov-commenter-bot"),
                False,
                id="not_github",
            ),
            pytest.param(
                "github",
                {"installation": GithubInstallationInfo(installation_id="some_id")},
                Token(username="test-codecov-commenter-bot"),
                False,
                id="has_installation",
            ),
            pytest.param(
                "github",
                {"installation": GithubInstallationInfo(installation_id="some_id")},
                None,
                False,
                id="not_using_commenter_bot",
            ),
        ],
    )
    def test_is_using_codecov_commenter(
        self,
        mocker,
        mock_configuration: dict[str, Any],
        service: str,
        data: dict[str, Any],
        bot_token: Token | None,
        expected_response,
    ) -> None:
        mock_repository_service: Any = mocker.MagicMock(spec=TorngitBaseAdapter)
        mock_repository_service.data = data
        mock_repository_service.service = service
        mock_repository_service.get_token_by_type.return_value = bot_token

        mock_configuration.params["github"] = {
            "bots": {"comment": {"username": "test-codecov-commenter-bot"}}
        }

        task = NotifyTask()
        assert (
            task.is_using_codecov_commenter(mock_repository_service)
            == expected_response
        )
