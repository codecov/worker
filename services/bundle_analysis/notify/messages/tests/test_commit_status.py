from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import async_to_sync
from shared.torngit.exceptions import TorngitClientError
from shared.typings.torngit import TorngitInstanceData
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.tests.factories.core import PullFactory
from services.bundle_analysis.notify.conftest import (
    get_commit_pair,
    get_enriched_pull_setting_up_mocks,
    get_report_pair,
    save_mock_bundle_analysis_report,
)
from services.bundle_analysis.notify.contexts.commit_status import (
    CommitStatusNotificationContext,
    CommitStatusNotificationContextBuilder,
)
from services.bundle_analysis.notify.messages.commit_status import (
    CommitStatusMessageStrategy,
)
from services.notification.notifiers.base import NotificationResult
from services.seats import SeatActivationInfo, ShouldActivateSeat


class FakeRedis(object):
    """
    This is a fake, very rudimentary redis implementation to ease the managing
     of mocking `set`, `get`.
    """

    def __init__(self) -> None:
        self.inner_dict = {}

    def set(self, key, ttl, value):
        self.inner_dict[key] = value

    def get(self, key):
        if key in self.inner_dict:
            return self.inner_dict[key]
        return None


@pytest.fixture
def mock_cache(mocker):
    fake_cache = mocker.MagicMock(name="fake_cache")
    fake_cache.get_backend.return_value = FakeRedis()
    mocker.patch(
        "services.bundle_analysis.notify.messages.commit_status.cache", fake_cache
    )
    return fake_cache


class TestCommitStatusMessage:
    @pytest.mark.parametrize(
        "user_config, expected",
        [
            pytest.param(
                {}, "Bundle change: -48.89% (Threshold: 5.0%)", id="default_config"
            ),
            pytest.param(
                {"bundle_analysis": {"warning_threshold": 500000}},
                "Bundle change: -372.56kB (Threshold: 500.0kB)",
                id="success_absolute_threshold",
            ),
            pytest.param(
                {"bundle_analysis": {"warning_threshold": 300000}},
                "Bundle change: -372.56kB (Threshold: 300.0kB)",
                id="warning_absolute_threshold",
            ),
        ],
    )
    def test_build_message_from_samples_negative_changes(
        self, user_config, expected, dbsession, mocker, mock_storage
    ):
        head_commit, base_commit = get_commit_pair(dbsession)
        repository = head_commit.repository
        head_commit_report, base_commit_report = get_report_pair(
            dbsession, (head_commit, base_commit)
        )
        save_mock_bundle_analysis_report(
            repository, head_commit_report, mock_storage, sample_report_number=2
        )
        save_mock_bundle_analysis_report(
            repository, base_commit_report, mock_storage, sample_report_number=1
        )
        enriched_pull = get_enriched_pull_setting_up_mocks(
            dbsession, mocker, (head_commit, base_commit)
        )
        user_yaml = UserYaml.from_dict(user_config)
        builder = CommitStatusNotificationContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mocker.patch(
            "services.bundle_analysis.comparison.get_appropriate_storage_service",
            return_value=mock_storage,
        )
        context = builder.build_context().get_result()
        message = CommitStatusMessageStrategy().build_message(context)
        assert message == expected

    @pytest.mark.parametrize(
        "user_config, expected",
        [
            pytest.param(
                {},
                "Passed with Warnings - Bundle change: 95.64% (Threshold: 5.0%)",
                id="default_config",
            ),
            pytest.param(
                {"bundle_analysis": {"warning_threshold": 500000}},
                "Bundle change: 372.56kB (Threshold: 500.0kB)",
                id="success_absolute_threshold",
            ),
            pytest.param(
                {"bundle_analysis": {"warning_threshold": 300000}},
                "Passed with Warnings - Bundle change: 372.56kB (Threshold: 300.0kB)",
                id="warning_absolute_threshold",
            ),
        ],
    )
    def test_build_message_from_samples(
        self, user_config, expected, dbsession, mocker, mock_storage
    ):
        head_commit, base_commit = get_commit_pair(dbsession)
        repository = head_commit.repository
        head_commit_report, base_commit_report = get_report_pair(
            dbsession, (head_commit, base_commit)
        )
        save_mock_bundle_analysis_report(
            repository, head_commit_report, mock_storage, sample_report_number=1
        )
        save_mock_bundle_analysis_report(
            repository, base_commit_report, mock_storage, sample_report_number=2
        )
        enriched_pull = get_enriched_pull_setting_up_mocks(
            dbsession, mocker, (head_commit, base_commit)
        )
        user_yaml = UserYaml.from_dict(user_config)
        builder = CommitStatusNotificationContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mocker.patch(
            "services.bundle_analysis.comparison.get_appropriate_storage_service",
            return_value=mock_storage,
        )
        context = builder.build_context().get_result()
        message = CommitStatusMessageStrategy().build_message(context)
        assert message == expected

    def _setup_send_message_tests(
        self, dbsession, mocker, torngit_ghapp_data, mock_storage
    ):
        fake_repo_provider = AsyncMock(
            name="fake_repo_provider",
            data=TorngitInstanceData(installation=torngit_ghapp_data),
        )
        fake_repo_provider.set_commit_status.return_value = {"id": 1000}
        mocker.patch(
            "services.bundle_analysis.notify.contexts.get_repo_provider_service",
            return_value=fake_repo_provider,
        )
        mocker.patch(
            "services.bundle_analysis.comparison.get_appropriate_storage_service",
            return_value=mock_storage,
        )
        head_commit, base_commit = get_commit_pair(dbsession)
        head_commit.parent_commit_id = base_commit.commitid
        dbsession.add_all([head_commit, base_commit])
        repository = head_commit.repository
        head_commit_report, base_commit_report = get_report_pair(
            dbsession, (head_commit, base_commit)
        )
        dbsession.add_all([head_commit_report, base_commit_report])
        save_mock_bundle_analysis_report(
            repository, head_commit_report, mock_storage, sample_report_number=1
        )
        save_mock_bundle_analysis_report(
            repository, base_commit_report, mock_storage, sample_report_number=2
        )
        mocker.patch(
            "services.bundle_analysis.notify.contexts.commit_status.fetch_and_update_pull_request_information_from_commit",
            return_value=None,
        )
        mocker.patch(
            "services.bundle_analysis.notify.contexts.commit_status.determine_seat_activation",
            return_value=SeatActivationInfo(
                should_activate_seat=ShouldActivateSeat.NO_ACTIVATE
            ),
        )
        user_yaml = UserYaml.from_dict({})
        builder = CommitStatusNotificationContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        return (
            fake_repo_provider,
            builder.build_context().get_result(),
            "Passed with Warnings - Bundle change: 95.64% (Threshold: 5.0%)",
        )

    @pytest.mark.parametrize(
        "torngit_ghapp_data",
        [
            pytest.param(None, id="no_app_used"),
            pytest.param(
                {
                    "installation_id": 123,
                    "id": 12,
                    "app_id": 12300,
                    "pem_path": "some_path",
                },
                id="some_app_used",
            ),
        ],
    )
    def test_send_message_success(
        self, dbsession, mocker, torngit_ghapp_data, mock_storage, mock_cache
    ):
        fake_repo_provider, context, message = self._setup_send_message_tests(
            dbsession, mocker, torngit_ghapp_data, mock_storage
        )
        strategy = CommitStatusMessageStrategy()
        result = async_to_sync(strategy.send_message)(context, message)
        fake_repo_provider.set_commit_status.assert_called_with(
            commit=context.commit.commitid,
            status="success",
            context="codecov/bundles",
            description=message,
            url=context.commit_status_url,
        )
        expected_app = torngit_ghapp_data.get("id") if torngit_ghapp_data else None
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            github_app_used=expected_app,
        )
        # Side effect of sending message is updating the cache
        assert mock_cache.get_backend().get(strategy._cache_key(context)) == message

    def test_send_message_fail(self, dbsession, mocker, mock_storage):
        fake_repo_provider, context, message = self._setup_send_message_tests(
            dbsession, mocker, None, mock_storage
        )
        fake_repo_provider.set_commit_status.side_effect = TorngitClientError()
        strategy = CommitStatusMessageStrategy()
        result = async_to_sync(strategy.send_message)(context, message)
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation="TorngitClientError",
        )

    def test_skip_payload_unchanged(self, dbsession, mocker, mock_storage, mock_cache):
        fake_repo_provider, context, message = self._setup_send_message_tests(
            dbsession, mocker, None, mock_storage
        )
        strategy = CommitStatusMessageStrategy()
        mock_cache.get_backend().set(strategy._cache_key(context), 600, message)
        result = async_to_sync(strategy.send_message)(context, message)
        fake_repo_provider.set_commit_status.assert_not_called()
        assert result == NotificationResult(
            notification_attempted=False,
            notification_successful=False,
            explanation="payload_unchanged",
        )
        # Side effect of sending message is updating the cache
        assert async_to_sync(strategy.send_message)(
            context, message
        ) == NotificationResult(
            notification_attempted=False,
            notification_successful=False,
            explanation="payload_unchanged",
        )


class TestCommitStatusUpgradeMessage:
    def test_build_upgrade_message(self, dbsession):
        head_commit, _ = get_commit_pair(dbsession)
        context = CommitStatusNotificationContext(
            head_commit, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        context.should_use_upgrade_comment = True
        context.pull = MagicMock(
            name="fake_pull",
            database_pull=PullFactory(),
            provider_pull={"author": {"username": "PR_author_username"}},
        )
        message = CommitStatusMessageStrategy().build_message(context)
        assert (
            message
            == "Please activate user PR_author_username to display a detailed status check"
        )
