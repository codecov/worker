from unittest.mock import MagicMock

import pytest
from shared.validation.types import BundleThreshold
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from services.bundle_analysis.notify.conftest import (
    get_commit_pair,
    get_report_pair,
    save_mock_bundle_analysis_report,
)
from services.bundle_analysis.notify.contexts import (
    ContextNotLoadedError,
    NotificationContextBuilder,
    NotificationContextBuildError,
)
from services.bundle_analysis.notify.types import NotificationUserConfig


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
            == "Property commit_report is not loaded. Make sure to build the context before using it."
        )

    @pytest.mark.parametrize(
        "field_name, expected",
        [
            ("commit_report", True),
            ("bundle_analysis_report", False),
            ("field_doesnt_exist", False),
        ],
    )
    def test_is_field_loaded(self, field_name, expected, dbsession):
        head_commit, _ = get_commit_pair(dbsession)
        builder = NotificationContextBuilder().initialize(
            head_commit, UserYaml.from_dict({}), GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        builder._notification_context.commit_report = MagicMock(
            name="fake_commit_report"
        )
        assert builder.is_field_loaded(field_name) == expected

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

    @pytest.mark.parametrize(
        "config, expected_user_config",
        [
            pytest.param(
                {
                    "comment": {
                        "layout": "reach,diff,flags,tree,reach",
                        "behavior": "default",
                        "show_carryforward_flags": False,
                    }
                },
                NotificationUserConfig(
                    required_changes=False,
                    warning_threshold=BundleThreshold("percentage", 5.0),
                    status_level="informational",
                    required_changes_threshold=BundleThreshold("absolute", 0),
                ),
                id="default_site_config",
            ),
            pytest.param(
                {"comment": False},
                NotificationUserConfig(
                    required_changes=False,
                    warning_threshold=BundleThreshold("percentage", 5.0),
                    status_level="informational",
                    required_changes_threshold=BundleThreshold("absolute", 0),
                ),
                id="comment_is_bool",
            ),
        ],
    )
    def test_build_context(
        self, dbsession, mock_storage, mocker, config, expected_user_config
    ):
        head_commit, base_commit = get_commit_pair(dbsession)
        head_commit_report, _ = get_report_pair(dbsession, (head_commit, base_commit))
        save_mock_bundle_analysis_report(
            head_commit.repository,
            head_commit_report,
            mock_storage,
            sample_report_number=1,
        )
        builder = NotificationContextBuilder().initialize(
            head_commit,
            UserYaml.from_dict(config),
            GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        )
        context = builder.build_context().get_result()
        assert context.commit_report == head_commit_report
        assert context.bundle_analysis_report.session_count() == 19
        assert context.user_config == expected_user_config
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
