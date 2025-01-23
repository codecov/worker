from textwrap import dedent
from unittest.mock import MagicMock

import pytest
from mock import AsyncMock
from shared.config import PATCH_CENTRIC_DEFAULT_CONFIG
from shared.torngit.exceptions import TorngitClientError
from shared.typings.torngit import TorngitInstanceData
from shared.validation.types import BundleThreshold
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.tests.factories.core import PullFactory
from services.bundle_analysis.notify.conftest import (
    get_commit_pair,
    get_enriched_pull_setting_up_mocks,
    get_report_pair,
    save_mock_bundle_analysis_report,
)
from services.bundle_analysis.notify.contexts.comment import (
    BundleAnalysisPRCommentContextBuilder,
    BundleAnalysisPRCommentNotificationContext,
)
from services.bundle_analysis.notify.messages.comment import (
    BundleAnalysisCommentMarkdownStrategy,
)
from services.bundle_analysis.notify.types import NotificationUserConfig
from services.notification.notifiers.base import NotificationResult
from tests.helpers import mock_all_plans_and_tiers


class TestCommentMesage:
    @pytest.mark.django_db
    def test_build_message_from_samples(self, dbsession, mocker, mock_storage):
        mock_all_plans_and_tiers()
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
        user_yaml = UserYaml.from_dict(PATCH_CENTRIC_DEFAULT_CONFIG)
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )

        context = builder.build_context().get_result()
        message = BundleAnalysisCommentMarkdownStrategy().build_message(context)
        assert message == dedent("""\
                ## [Bundle](https://app.codecov.io/gh/{owner}/{repo}/pull/{pullid}?dropdown=bundle) Report

                Changes will decrease total bundle size by 372.56kB (-48.89%) :arrow_down:. This is within the [configured](https://docs.codecov.com/docs/javascript-bundle-analysis#main-features) threshold :white_check_mark:

                <details><summary>Detailed changes</summary>

                | Bundle name | Size | Change |
                | ----------- | ---- | ------ |
                | @codecov/sveltekit-plugin-esm | 1.1kB | 188 bytes (20.68%) :arrow_up: |
                | @codecov/rollup-plugin-esm | 1.32kB | 1.01kB (-43.37%) :arrow_down: |
                | @codecov/bundler-plugin-core-esm | 8.2kB | 30.02kB (-78.55%) :arrow_down: |
                | @codecov/bundler-plugin-core-cjs | 43.32kB | 611 bytes (1.43%) :arrow_up: |
                | @codecov/example-next-app-server-cjs | (removed) | 342.32kB (-100.0%) :arrow_down: |

                </details>
                """).format(
            pullid=enriched_pull.database_pull.pullid,
            owner=head_commit.repository.owner.username,
            repo=head_commit.repository.name,
        )

    def _setup_send_message_tests(
        self, dbsession, mocker, torngit_ghapp_data, bundle_analysis_commentid
    ):
        fake_repo_provider = MagicMock(
            name="fake_repo_provider",
            data=TorngitInstanceData(installation=torngit_ghapp_data),
            post_comment=AsyncMock(),
            edit_comment=AsyncMock(),
        )
        fake_repo_provider.post_comment.return_value = {"id": 1000}
        fake_repo_provider.edit_comment.return_value = {"id": 1000}
        mocker.patch(
            "services.bundle_analysis.notify.contexts.get_repo_provider_service",
            return_value=fake_repo_provider,
        )
        head_commit, _ = get_commit_pair(dbsession)
        context = BundleAnalysisPRCommentNotificationContext(
            head_commit, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mock_pull = MagicMock(
            name="fake_pull",
            database_pull=MagicMock(
                name="fake_database_pull",
                bundle_analysis_commentid=bundle_analysis_commentid,
                pullid=12,
            ),
        )
        context.__dict__["pull"] = mock_pull
        context.__dict__["user_config"] = NotificationUserConfig(
            warning_threshold=BundleThreshold("absolute", 0),
            required_changes_threshold=BundleThreshold("absolute", 0),
            required_changes=False,
            status_level="informational",
        )
        mock_comparison = MagicMock(name="fake_bundle_analysis_comparison")
        context.__dict__["bundle_analysis_comparison"] = mock_comparison
        message = "carefully crafted message"
        return (fake_repo_provider, mock_pull, context, message)

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
    def test_send_message_no_exising_comment(
        self, dbsession, mocker, torngit_ghapp_data
    ):
        fake_repo_provider, mock_pull, context, message = (
            self._setup_send_message_tests(
                dbsession, mocker, torngit_ghapp_data, bundle_analysis_commentid=None
            )
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = strategy.send_message(context, message)
        expected_app = torngit_ghapp_data.get("id") if torngit_ghapp_data else None
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            github_app_used=expected_app,
        )
        fake_repo_provider.post_comment.assert_called_with(12, message)
        fake_repo_provider.edit_message.assert_not_called()
        assert mock_pull.database_pull.bundle_analysis_commentid == 1000

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
    def test_send_message_exising_comment(self, dbsession, mocker, torngit_ghapp_data):
        fake_repo_provider, _, context, message = self._setup_send_message_tests(
            dbsession, mocker, torngit_ghapp_data, bundle_analysis_commentid=1000
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = strategy.send_message(context, message)
        expected_app = torngit_ghapp_data.get("id") if torngit_ghapp_data else None
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            github_app_used=expected_app,
        )
        fake_repo_provider.edit_comment.assert_called_with(12, 1000, message)
        fake_repo_provider.post_comment.assert_not_called()

    def test_send_message_fail(self, dbsession, mocker):
        fake_repo_provider, _, context, message = self._setup_send_message_tests(
            dbsession, mocker, None, bundle_analysis_commentid=None
        )
        fake_repo_provider.post_comment.side_effect = TorngitClientError()
        context.__dict__["commit_report"] = MagicMock(
            name="fake_commit_report", external_id="some_UUID4"
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = strategy.send_message(context, message)
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation="TorngitClientError",
        )


class TestUpgradeMessage:
    def test_build_upgrade_message_cloud(self, dbsession, mocker):
        head_commit, _ = get_commit_pair(dbsession)
        context = BundleAnalysisPRCommentNotificationContext(
            head_commit, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        context.should_use_upgrade_comment = True
        context.pull = MagicMock(
            name="fake_pull",
            database_pull=PullFactory(),
            provider_pull={"author": {"username": "PR_author_username"}},
        )
        mocker.patch(
            "services.bundle_analysis.notify.messages.comment.requires_license",
            return_value=False,
        )
        mocker.patch(
            "services.bundle_analysis.notify.messages.comment.get_members_url",
            return_value="http://members_url",
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = strategy.build_message(context)
        assert result == dedent("""\
            The author of this PR, PR_author_username, is not an activated member of this organization on Codecov.
            Please [activate this user](http://members_url) to display this PR comment.
            Bundle data is still being uploaded to Codecov for purposes of overall calculations.

            Please don't hesitate to email us at support@codecov.io with any questions.
            """)

    def test_build_upgrade_message_self_hosted(self, dbsession, mocker):
        head_commit, _ = get_commit_pair(dbsession)
        context = BundleAnalysisPRCommentNotificationContext(
            head_commit, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        context.should_use_upgrade_comment = True
        context.pull = MagicMock(
            name="fake_pull",
            database_pull=PullFactory(),
            provider_pull={"author": {"username": "PR_author_username"}},
        )
        mocker.patch(
            "services.bundle_analysis.notify.messages.comment.requires_license",
            return_value=True,
        )
        mocker.patch(
            "services.bundle_analysis.notify.messages.comment.get_members_url",
            return_value="http://members_url",
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = strategy.build_message(context)
        assert result == dedent("""\
            The author of this PR, PR_author_username, is not activated in your Codecov Self-Hosted installation.
            Please [activate this user](http://members_url) to display this PR comment.
            Bundle data is still being uploaded to your instance of Codecov for purposes of overall calculations.

            Please contact your Codecov On-Premises installation administrator with any questions.
            """)
