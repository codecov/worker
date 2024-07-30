from unittest.mock import AsyncMock, MagicMock

import pytest
from django.template import loader
from shared.torngit.exceptions import TorngitClientError
from shared.typings.torngit import TorngitInstanceData
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from services.bundle_analysis.new_notify.conftest import (
    get_commit_pair,
    get_enriched_pull_setting_up_mocks,
    get_report_pair,
    save_mock_bundle_analysis_report,
)
from services.bundle_analysis.new_notify.contexts.comment import (
    BundleAnalysisCommentContextBuilder,
    BundleAnalysisCommentNotificationContext,
)
from services.bundle_analysis.new_notify.helpers import bytes_readable
from services.bundle_analysis.new_notify.messages.comment import (
    BundleAnalysisCommentMarkdownStrategy,
    BundleCommentTemplateContext,
    BundleRow,
)
from services.notification.notifiers.base import NotificationResult


class TestCommentMesage:
    @pytest.mark.parametrize(
        "total_size_delta, summary_line",
        [
            pytest.param(
                100,
                "Changes will increase total bundle size by 100 bytes :arrow_up:",
                id="increase_100b",
            ),
            pytest.param(
                1234,
                "Changes will increase total bundle size by 1.23kB :arrow_up:",
                id="increase_1.23kB",
            ),
            pytest.param(
                1e6 + 500,
                "Changes will increase total bundle size by 1.0MB :arrow_up:",
                id="increase_1MB",
            ),
            pytest.param(
                0, "Bundle size has no change :white_check_mark:", id="no_change"
            ),
            pytest.param(
                -100,
                "Changes will decrease total bundle size by 100 bytes :arrow_down:",
                id="decrease_100b",
            ),
            pytest.param(
                -1234,
                "Changes will decrease total bundle size by 1.23kB :arrow_down:",
                id="decrease_1.23kB",
            ),
            pytest.param(
                -1e6 - 500,
                "Changes will decrease total bundle size by 1.0MB :arrow_down:",
                id="decrease_1MB",
            ),
        ],
    )
    def test_summary_change_line_template(self, total_size_delta, summary_line):
        template = loader.get_template("bundle_analysis_notify/bundle_comment.md")
        context = BundleCommentTemplateContext(
            pull_url="example.url",
            bundle_rows=[],
            total_size_delta=total_size_delta,
            total_size_readable=bytes_readable(total_size_delta),
        )
        expected = (
            "## [Bundle](example.url) Report\n"
            + "\n"
            + summary_line
            + "\n"
            + "\n| Bundle name | Size | Change |"
            + "\n| ----------- | ---- | ------ |\n"
        )
        assert template.render(context) == expected

    def test_bundle_change_row_template(self):
        template = loader.get_template("bundle_analysis_notify/bundle_table.md")
        context = {
            "bundle_rows": [
                BundleRow(
                    bundle_name="@test/increase",
                    bundle_size="50kB",
                    change_size_readable="100 bytes",
                    change_icon=":arrow_up:",
                ),
                BundleRow(
                    bundle_name="@test/decrease",
                    bundle_size="50kB",
                    change_size_readable="100 bytes",
                    change_icon=":arrow_down:",
                ),
                BundleRow(
                    bundle_name="@test/removed",
                    bundle_size="(removed)",
                    change_size_readable="100 bytes",
                    change_icon=":arrow_down:",
                ),
            ]
        }
        expected = (
            "| Bundle name | Size | Change |"
            + "\n| ----------- | ---- | ------ |"
            + "\n| @test/increase | 50kB | 100 bytes :arrow_up: |"
            + "\n| @test/decrease | 50kB | 100 bytes :arrow_down: |"
            + "\n| @test/removed | (removed) | 100 bytes :arrow_down: |"
            + "\n"
        )
        assert template.render(context) == expected

    def test_build_message_from_samples(self, dbsession, mocker, mock_storage):
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
        user_yaml = UserYaml.from_dict({})
        builder = BundleAnalysisCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mocker.patch(
            "services.bundle_analysis.comparison.get_appropriate_storage_service",
            return_value=mock_storage,
        )
        context = builder.build_context().get_result()
        message = BundleAnalysisCommentMarkdownStrategy().build_message(context)
        assert (
            message
            == """## [Bundle](https://app.codecov.io/gh/{owner}/{repo}/pull/{pullid}?dropdown=bundle) Report

Changes will decrease total bundle size by 372.56kB :arrow_down:

| Bundle name | Size | Change |
| ----------- | ---- | ------ |
| @codecov/remix-vite-plugin-cjs | 1.32kB | 0 bytes  |
| @codecov/remix-vite-plugin-esm | 975 bytes | 0 bytes  |
| @codecov/example-next-app-edge-server-array-push | 354 bytes | 0 bytes  |
| @codecov/sveltekit-plugin-esm | 1.1kB | 188 bytes :arrow_up: |
| @codecov/rollup-plugin-esm | 1.32kB | 1.01kB :arrow_down: |
| @codecov/webpack-plugin-cjs | 3.77kB | 0 bytes  |
| @codecov/rollup-plugin-cjs | 2.82kB | 0 bytes  |
| @codecov/nuxt-plugin-cjs | 1.41kB | 0 bytes  |
| @codecov/nuxt-plugin-esm | 855 bytes | 0 bytes  |
| @codecov/example-webpack-app-array-push | 71.19kB | 0 bytes  |
| @codecov/bundler-plugin-core-esm | 8.2kB | 30.02kB :arrow_down: |
| @codecov/webpack-plugin-esm | 1.44kB | 0 bytes  |
| @codecov/sveltekit-plugin-cjs | 1.33kB | 0 bytes  |
| @codecov/vite-plugin-cjs | 2.8kB | 0 bytes  |
| @codecov/vite-plugin-esm | 1.26kB | 0 bytes  |
| @codecov/example-rollup-app-iife | 95.46kB | 0 bytes  |
| @codecov/example-vite-app-esm | 150.61kB | 0 bytes  |
| @codecov/bundler-plugin-core-cjs | 43.32kB | 611 bytes :arrow_up: |
| @codecov/example-next-app-server-cjs | (removed) | 342.32kB :arrow_down: |
""".format(
                pullid=enriched_pull.database_pull.pullid,
                owner=head_commit.repository.owner.username,
                repo=head_commit.repository.name,
            )
        )

    def _setup_send_message_tests(
        self, dbsession, mocker, torngit_ghapp_data, bundle_analysis_commentid
    ):
        fake_repo_provider = AsyncMock(
            name="fake_repo_provider",
            data=TorngitInstanceData(installation=torngit_ghapp_data),
        )
        fake_repo_provider.post_comment.return_value = {"id": 1000}
        fake_repo_provider.edit_comment.return_value = {"id": 1000}
        mocker.patch(
            "services.bundle_analysis.new_notify.contexts.get_repo_provider_service",
            return_value=fake_repo_provider,
        )
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict({})
        context = BundleAnalysisCommentNotificationContext(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mock_pull = MagicMock(
            name="fake_pull",
            database_pull=MagicMock(
                name="fake_database_pull",
                bundle_analysis_commentid=bundle_analysis_commentid,
                pullid=12,
            ),
        )
        context._pull = mock_pull
        mock_comparison = MagicMock(name="fake_bundle_analysis_comparison")
        context._bundle_analysis_comparison = mock_comparison
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
                id="no_app_used",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_send_message_no_exising_comment(
        self, dbsession, mocker, torngit_ghapp_data
    ):
        fake_repo_provider, mock_pull, context, message = (
            self._setup_send_message_tests(
                dbsession, mocker, torngit_ghapp_data, bundle_analysis_commentid=None
            )
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = await strategy.send_message(context, message)
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
                id="no_app_used",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_send_message_exising_comment(
        self, dbsession, mocker, torngit_ghapp_data
    ):
        fake_repo_provider, _, context, message = self._setup_send_message_tests(
            dbsession, mocker, torngit_ghapp_data, bundle_analysis_commentid=1000
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = await strategy.send_message(context, message)
        expected_app = torngit_ghapp_data.get("id") if torngit_ghapp_data else None
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            github_app_used=expected_app,
        )
        fake_repo_provider.edit_comment.assert_called_with(12, 1000, message)
        fake_repo_provider.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_fail(self, dbsession, mocker):
        fake_repo_provider, _, context, message = self._setup_send_message_tests(
            dbsession, mocker, None, bundle_analysis_commentid=None
        )
        fake_repo_provider.post_comment.side_effect = TorngitClientError()
        context._commit_report = MagicMock(
            name="fake_commit_report", external_id="some_UUID4"
        )
        strategy = BundleAnalysisCommentMarkdownStrategy()
        result = await strategy.send_message(context, message)
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation="TorngitClientError",
        )
