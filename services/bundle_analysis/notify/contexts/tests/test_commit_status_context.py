from unittest.mock import MagicMock

import pytest
from shared.validation.types import BundleThreshold
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.tests.factories.core import CommitFactory
from services.bundle_analysis.comparison import ComparisonLoader
from services.bundle_analysis.notify.conftest import (
    get_commit_pair,
    get_enriched_pull_setting_up_mocks,
    get_report_pair,
    save_mock_bundle_analysis_report,
)
from services.bundle_analysis.notify.contexts import (
    ContextNotLoadedError,
    NotificationContextBuildError,
)
from services.bundle_analysis.notify.contexts.commit_status import (
    CommitStatusLevel,
    CommitStatusNotificationContextBuilder,
)
from services.bundle_analysis.notify.types import NotificationUserConfig


class TestBundleAnalysisPRCommentNotificationContext:
    @pytest.mark.asyncio
    async def test_load_pull_not_found(self, dbsession, mocker):
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict({})
        fake_repo_service = mocker.MagicMock(name="fake_repo_service")
        mock_fetch_pr = mocker.patch(
            "services.bundle_analysis.notify.contexts.commit_status.fetch_and_update_pull_request_information_from_commit",
            return_value=None,
        )
        mocker.patch(
            "services.bundle_analysis.notify.contexts.get_repo_provider_service",
            return_value=fake_repo_service,
        )
        builder = CommitStatusNotificationContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        await builder.load_optional_enriched_pull()
        assert builder._notification_context.pull is None
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
        builder = CommitStatusNotificationContextBuilder().initialize(
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
            await builder.load_optional_enriched_pull()
            builder.load_bundle_comparison()
        assert builder._notification_context.pull is not None
        assert exp.value.failed_step == "load_bundle_comparison"
        assert exp.value.detail == expected_missing_detail

    @pytest.mark.asyncio
    async def test_load_bundle_comparison_when_pull_is_none(
        self, dbsession, mocker, mock_storage
    ):
        head_commit, base_commit = get_commit_pair(dbsession)
        repository = head_commit.repository
        head_commit.parent_commit_id = base_commit.commitid
        head_report, base_report = get_report_pair(
            dbsession, (head_commit, base_commit)
        )
        mocker.patch(
            "services.bundle_analysis.notify.contexts.commit_status.fetch_and_update_pull_request_information_from_commit",
            return_value=None,
        )
        mocker.patch(
            "services.bundle_analysis.notify.contexts.get_repo_provider_service",
            return_value=mocker.MagicMock(name="fake_repo_service"),
        )

        mock_check_compare_sha = mocker.patch(
            "shared.bundle_analysis.comparison.BundleAnalysisComparison._check_compare_sha",
            return_value=None,
        )

        save_mock_bundle_analysis_report(
            repository, head_report, mock_storage, sample_report_number=2
        )
        save_mock_bundle_analysis_report(
            repository, base_report, mock_storage, sample_report_number=1
        )
        user_yaml = UserYaml.from_dict({})
        builder = CommitStatusNotificationContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        builder.load_commit_report()
        await builder.load_optional_enriched_pull()
        builder.load_bundle_comparison()
        context = builder.get_result()
        assert context.pull is None
        assert context.bundle_analysis_comparison is not None
        assert (
            context.bundle_analysis_comparison.base_report_key
            == base_report.external_id
        )
        assert (
            context.bundle_analysis_comparison.head_report_key
            == head_report.external_id
        )

    @pytest.mark.parametrize(
        "yaml_dict, percent_change, absolute_change, expected",
        [
            pytest.param(
                {},
                1.0,
                10000,
                CommitStatusLevel.INFO,
                id="default_config_within_5%_change",
            ),
            pytest.param(
                {},
                5.5,
                10000,
                CommitStatusLevel.WARNING,
                id="default_config_outside_5%_change",
            ),
            pytest.param(
                {"bundle_analysis": {"warning_threshold": 10000}},
                1.0,
                10001,
                CommitStatusLevel.WARNING,
                id="informational_outside_range",
            ),
            pytest.param(
                {"bundle_analysis": {"warning_threshold": 10000}},
                1.0,
                10000,
                CommitStatusLevel.INFO,
                id="informational_within_range",
            ),
            pytest.param(
                {"bundle_analysis": {"warning_threshold": 10000, "status": True}},
                1.0,
                10001,
                CommitStatusLevel.ERROR,
                id="fail_outside_range_absolute",
            ),
            pytest.param(
                {"bundle_analysis": {"status": True}},
                5.1,
                10000,
                CommitStatusLevel.ERROR,
                id="fail_outside_range_percentage",
            ),
        ],
    )
    def test_load_commit_status_level(
        self, yaml_dict, percent_change, absolute_change, expected, dbsession, mocker
    ):
        head_commit = CommitFactory()
        dbsession.add(head_commit)
        user_yaml = UserYaml.from_dict(yaml_dict)
        builder = CommitStatusNotificationContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        builder.load_user_config()
        builder._notification_context.bundle_analysis_comparison = mocker.MagicMock(
            name="fake_comparison",
            total_size_delta=absolute_change,
            percentage_delta=percent_change,
        )
        builder.load_commit_status_level()
        context = builder.get_result()
        assert context.commit_status_level == expected

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
        builder = CommitStatusNotificationContextBuilder().initialize(
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
        assert context.user_config == NotificationUserConfig(
            required_changes=False,
            warning_threshold=BundleThreshold("percentage", 5.0),
            status_level="informational",
            required_changes_threshold=BundleThreshold("absolute", 0),
        )
        assert context.commit_status_level == CommitStatusLevel.INFO
        assert context.cache_ttl == 600
        assert context.commit_status_url is not None

    def test_initialize_from_context(self, dbsession, mocker):
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict({})
        builder = CommitStatusNotificationContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        context = builder.get_result()
        context.commit_report = MagicMock(name="fake_commit_report")
        context.bundle_analysis_report = MagicMock(name="fake_bundle_analysis_report")
        context.pull = MagicMock(name="fake_pull")

        other_builder = (
            CommitStatusNotificationContextBuilder().initialize_from_context(
                user_yaml, context
            )
        )
        other_context = other_builder.get_result()

        assert context.commit == other_context.commit
        assert context.commit_report == other_context.commit_report
        assert context.bundle_analysis_report == other_context.bundle_analysis_report
        assert context.pull == other_context.pull
        with pytest.raises(ContextNotLoadedError):
            other_context.bundle_analysis_comparison

        fake_comparison = MagicMock(
            name="fake_comparison", total_size_delta=1000, percentage_delta=1
        )
        mocker.patch.object(
            ComparisonLoader, "get_comparison", return_value=fake_comparison
        )
        other_context = other_builder.build_context().get_result()

        assert context.commit == other_context.commit
        assert context.commit_report == other_context.commit_report
        assert context.bundle_analysis_report == other_context.bundle_analysis_report
        assert context.pull == other_context.pull
        assert other_context.bundle_analysis_comparison == fake_comparison
