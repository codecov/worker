from unittest.mock import MagicMock

import pytest
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.tests.factories.core import CommitFactory
from services.bundle_analysis.new_notify.conftest import (
    get_commit_pair,
    get_enriched_pull_setting_up_mocks,
    get_report_pair,
    save_mock_bundle_analysis_report,
)
from services.bundle_analysis.new_notify.contexts import (
    ContextNotLoadedError,
    NotificationContextBuilder,
    NotificationContextBuildError,
)
from services.bundle_analysis.new_notify.contexts.comment import (
    BundleAnalysisCommentContextBuilder,
)


class TestBaseBundleAnalysisNotificationContextBuild:
    def test_access_not_loaded_field_raises(self, dbsession):
        head_commit, _ = get_commit_pair(dbsession)
        builder = NotificationContextBuilder().initialize(
            head_commit, UserYaml.from_dict({}), GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        with pytest.raises(ContextNotLoadedError) as exp:
            builder._notification_context.commit_report
        assert (
            str(exp.value)
            == "The property you are trying to access is not loaded. Make sure to build the context before using it."
        )

    def test_load_commit_report_no_report(self, dbsession):
        head_commit, _ = get_commit_pair(dbsession)
        builder = NotificationContextBuilder().initialize(
            head_commit, UserYaml.from_dict({}), GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        with pytest.raises(NotificationContextBuildError) as exp:
            builder.load_commit_report()
        assert exp.value.failed_step == "load_commit_report"

    def test_load_bundle_analysis_report_no_report(self, dbsession, mock_storage):
        head_commit, base_commit = get_commit_pair(dbsession)
        get_report_pair(dbsession, (head_commit, base_commit))
        builder = NotificationContextBuilder().initialize(
            head_commit, UserYaml.from_dict({}), GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        with pytest.raises(NotificationContextBuildError) as exp:
            builder.load_commit_report()
            builder.load_bundle_analysis_report()
        assert exp.value.failed_step == "load_bundle_analysis_report"

    def test_build_context(self, dbsession, mock_storage, mocker):
        head_commit, base_commit = get_commit_pair(dbsession)
        head_commit_report, _ = get_report_pair(dbsession, (head_commit, base_commit))
        save_mock_bundle_analysis_report(
            head_commit.repository,
            head_commit_report,
            mock_storage,
            sample_report_number=1,
        )
        builder = NotificationContextBuilder().initialize(
            head_commit, UserYaml.from_dict({}), GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        context = builder.build_context().get_result()
        assert context.commit_report == head_commit_report
        assert context.bundle_analysis_report.session_count() == 19
        assert [
            bundle_report.name
            for bundle_report in context.bundle_analysis_report.bundle_reports()
        ] == [
            "@codecov/sveltekit-plugin-cjs",
            "@codecov/webpack-plugin-cjs",
            "@codecov/webpack-plugin-esm",
            "@codecov/vite-plugin-esm",
            "@codecov/bundler-plugin-core-esm",
            "@codecov/remix-vite-plugin-esm",
            "@codecov/nuxt-plugin-esm",
            "@codecov/rollup-plugin-esm",
            "@codecov/example-webpack-app-array-push",
            "@codecov/remix-vite-plugin-cjs",
            "@codecov/nuxt-plugin-cjs",
            "@codecov/example-vite-app-esm",
            "@codecov/example-next-app-edge-server-array-push",
            "@codecov/rollup-plugin-cjs",
            "@codecov/sveltekit-plugin-esm",
            "@codecov/vite-plugin-cjs",
            "@codecov/bundler-plugin-core-cjs",
            "@codecov/example-rollup-app-iife",
            "@codecov/example-next-app-server-cjs",
        ]


class TestBundleAnalysisCommentNotificationContext:
    @pytest.mark.asyncio
    async def test_load_pull_not_found(self, dbsession, mocker):
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict({})
        fake_repo_service = mocker.MagicMock(name="fake_repo_service")
        mock_fetch_pr = mocker.patch(
            "services.bundle_analysis.new_notify.contexts.comment.fetch_and_update_pull_request_information_from_commit",
            return_value=None,
        )
        mocker.patch(
            "services.bundle_analysis.new_notify.contexts.get_repo_provider_service",
            return_value=fake_repo_service,
        )
        builder = BundleAnalysisCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        with pytest.raises(NotificationContextBuildError) as exp:
            await builder.load_enriched_pull()
        assert exp.value.failed_step == "load_enriched_pull"
        mock_fetch_pr.assert_called_with(fake_repo_service, head_commit, user_yaml)

    @pytest.mark.parametrize(
        "expected_missing_detail",
        [
            pytest.param("MissingBaseCommit"),
            pytest.param("MissingHeadCommit"),
            pytest.param("MissingBaseReport"),
            pytest.param("MissingHeadReport"),
        ],
    )
    @pytest.mark.asyncio
    async def test_load_bundle_comparison_missing_some_info(
        self, expected_missing_detail, dbsession, mocker
    ):
        head_commit, base_commit = get_commit_pair(dbsession)
        sink_commit = CommitFactory(repository=head_commit.repository)
        dbsession.add(sink_commit)
        get_report_pair(dbsession, (head_commit, base_commit))
        enriched_pull = get_enriched_pull_setting_up_mocks(
            dbsession, mocker, (head_commit, base_commit)
        )
        user_yaml = UserYaml.from_dict({})
        builder = BundleAnalysisCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        builder.load_commit_report()
        match expected_missing_detail:
            case "MissingBaseCommit":
                enriched_pull.database_pull.compared_to = None
            case "MissingHeadCommit":
                enriched_pull.database_pull.head = None
            case "MissingBaseReport":
                # Deleting the BaseReport also deleted base_commit
                # So instead we point the Pull object to a commit that doesn't have reports
                enriched_pull.database_pull.compared_to = sink_commit.commitid
            case "MissingHeadReport":
                enriched_pull.database_pull.head = sink_commit.commitid

        with pytest.raises(NotificationContextBuildError) as exp:
            await builder.load_enriched_pull()
            builder.load_bundle_comparison()
        assert exp.value.failed_step == "load_bundle_comparison"
        assert exp.value.detail == expected_missing_detail

    @pytest.mark.parametrize(
        "config, total_size_delta",
        [
            pytest.param(
                {
                    "comment": {
                        "require_bundle_changes": "bundle_increase",
                        "bundle_change_threshold": 1000000,
                    }
                },
                100,
                id="required_increase_with_big_threshold",
            ),
            pytest.param(
                {
                    "comment": {
                        "require_bundle_changes": "bundle_increase",
                        "bundle_change_threshold": 10,
                    }
                },
                -100,
                id="required_increase_but_decreased",
            ),
            pytest.param(
                {
                    "comment": {
                        "require_bundle_changes": True,
                        "bundle_change_threshold": 1000000,
                    }
                },
                100,
                id="required_changes_with_big_threshold",
            ),
        ],
    )
    def test_evaluate_changes_fail(self, config, total_size_delta, dbsession, mocker):
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict(config)
        builder = BundleAnalysisCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mock_pull = MagicMock(
            name="fake_pull",
            database_pull=MagicMock(bundle_analysis_commentid=None, id=12),
        )
        builder._notification_context.pull = mock_pull
        mock_comparison = MagicMock(
            name="fake_bundle_analysis_comparison", total_size_delta=total_size_delta
        )
        builder._notification_context.bundle_analysis_comparison = mock_comparison
        with pytest.raises(NotificationContextBuildError) as exp:
            builder.evaluate_has_enough_changes()
        assert exp.value.failed_step == "evaluate_has_enough_changes"

    @pytest.mark.parametrize(
        "config, total_size_delta",
        [
            pytest.param({}, 100, id="default_config"),
            pytest.param(
                {"comment": {"require_bundle_changes": False}},
                100,
                id="no_required_changes",
            ),
            pytest.param(
                {"comment": {"require_bundle_changes": True}},
                100,
                id="required_changes_increase",
            ),
            pytest.param(
                {"comment": {"require_bundle_changes": True}},
                -100,
                id="required_changes_decrease",
            ),
            pytest.param(
                {"comment": {"require_bundle_changes": "bundle_increase"}},
                100,
                id="required_increase",
            ),
            pytest.param(
                {
                    "comment": {
                        "require_bundle_changes": "bundle_increase",
                        "bundle_change_threshold": 1000,
                    }
                },
                1001,
                id="required_increase_with_small_threshold",
            ),
        ],
    )
    def test_evaluate_changes_success(self, config, total_size_delta, dbsession):
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict(config)
        builder = BundleAnalysisCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mock_pull = MagicMock(
            name="fake_pull",
            database_pull=MagicMock(bundle_analysis_commentid=None, id=12),
        )
        builder._notification_context.pull = mock_pull
        mock_comparison = MagicMock(
            name="fake_bundle_analysis_comparison", total_size_delta=total_size_delta
        )
        builder._notification_context.bundle_analysis_comparison = mock_comparison
        result = builder.evaluate_has_enough_changes()
        assert result == builder

    def test_evaluate_changes_comment_exists(self, dbsession):
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict(
            {
                "comment": {
                    "require_bundle_changes": "bundle_increase",
                    "bundle_change_threshold": 1000000,
                }
            }
        )
        builder = BundleAnalysisCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mock_pull = MagicMock(
            name="fake_pull",
            database_pull=MagicMock(bundle_analysis_commentid=12345, id=12),
        )
        builder._notification_context.pull = mock_pull
        mock_comparison = MagicMock(
            name="fake_bundle_analysis_comparison", total_size_delta=100
        )
        builder._notification_context.bundle_analysis_comparison = mock_comparison
        result = builder.evaluate_has_enough_changes()
        assert result == builder

    def test_build_context(self, dbsession, mocker, mock_storage):
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
        assert context.commit_report == head_commit_report
        assert context.bundle_analysis_report.session_count() == 18
        assert context.pull == enriched_pull
        assert (
            context.bundle_analysis_comparison.base_report_key
            == base_commit_report.external_id
        )
        assert (
            context.bundle_analysis_comparison.head_report_key
            == head_commit_report.external_id
        )
