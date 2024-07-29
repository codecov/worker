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
    NotificationContextBuilder,
    NotificationContextBuildError,
)
from services.bundle_analysis.new_notify.contexts.comment import (
    BundleAnalysisCommentContextBuilder,
)


class TestBaseBundleAnalysisNotificationContextBuild:
    def test_load_commit_report_no_report(self, dbsession):
        head_commit, _ = get_commit_pair(dbsession)
        builder = NotificationContextBuilder().initialize(
            head_commit, UserYaml.from_dict({}), GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        with pytest.raises(NotificationContextBuildError) as exp:
            builder.load_commit_report()
        assert exp.value.failed_step == "load_commit_report"

    def test_load_bundle_analysis_report_no_report(self, dbsession):
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
