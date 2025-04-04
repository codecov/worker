from unittest.mock import MagicMock

import pytest
from shared.config import PATCH_CENTRIC_DEFAULT_CONFIG
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.tests.factories.core import CommitFactory, PullFactory
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
from services.bundle_analysis.notify.contexts.comment import (
    BundleAnalysisPRCommentContextBuilder,
)
from services.repository import EnrichedPull
from services.seats import SeatActivationInfo, ShouldActivateSeat
from tests.helpers import mock_all_plans_and_tiers


class TestBundleAnalysisPRCommentNotificationContext:
    @pytest.mark.asyncio
    async def test_load_pull_not_found(self, dbsession, mocker):
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict({})
        fake_repo_service = mocker.MagicMock(name="fake_repo_service")
        mock_fetch_pr = mocker.patch(
            "services.bundle_analysis.notify.contexts.comment.fetch_and_update_pull_request_information_from_commit",
            return_value=None,
        )
        mocker.patch(
            "services.bundle_analysis.notify.contexts.get_repo_provider_service",
            return_value=fake_repo_service,
        )
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
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
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
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
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        builder.load_user_config()
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
            pytest.param(
                PATCH_CENTRIC_DEFAULT_CONFIG,
                100,
                id="default_config",
            ),
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
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        builder.load_user_config()
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
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        builder.load_user_config()
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

    @pytest.mark.parametrize(
        "activation_result, auto_activate_succeeds, expected",
        [
            (ShouldActivateSeat.AUTO_ACTIVATE, True, False),
            (ShouldActivateSeat.AUTO_ACTIVATE, False, True),
            (ShouldActivateSeat.MANUAL_ACTIVATE, False, True),
            (ShouldActivateSeat.NO_ACTIVATE, False, False),
        ],
    )
    def test_evaluate_should_use_upgrade_message(
        self, activation_result, dbsession, auto_activate_succeeds, expected, mocker
    ):
        activation_result = SeatActivationInfo(
            should_activate_seat=activation_result,
            owner_id=1,
            author_id=10,
            reason="mocked",
        )
        mocker.patch(
            "services.seats.determine_seat_activation",
            return_value=activation_result,
        )
        mocker.patch(
            "services.seats.activate_user",
            return_value=auto_activate_succeeds,
        )
        mocker.patch(
            "services.seats.schedule_new_user_activated_task",
            return_value=auto_activate_succeeds,
        )
        head_commit, _ = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict({})
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        mock_pull = MagicMock(
            name="fake_pull",
            database_pull=MagicMock(bundle_analysis_commentid=12345, id=12),
        )
        builder._notification_context.pull = mock_pull
        builder.evaluate_should_use_upgrade_message()
        assert builder._notification_context.should_use_upgrade_comment == expected

    @pytest.mark.django_db
    def test_build_context(self, dbsession, mocker, mock_storage):
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

    @pytest.mark.django_db
    def test_initialize_from_context(self, dbsession, mocker):
        mock_all_plans_and_tiers()
        head_commit, base_commit = get_commit_pair(dbsession)
        user_yaml = UserYaml.from_dict(PATCH_CENTRIC_DEFAULT_CONFIG)
        builder = BundleAnalysisPRCommentContextBuilder().initialize(
            head_commit, user_yaml, GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        context = builder.get_result()
        context.commit_report = MagicMock(name="fake_commit_report")
        context.bundle_analysis_report = MagicMock(name="fake_bundle_analysis_report")

        pull = PullFactory(
            repository=base_commit.repository,
            head=head_commit.commitid,
            base=base_commit.commitid,
            compared_to=base_commit.commitid,
        )
        dbsession.add(pull)
        dbsession.commit()
        context.pull = EnrichedPull(
            database_pull=pull,
            provider_pull={},
        )

        other_builder = BundleAnalysisPRCommentContextBuilder().initialize_from_context(
            user_yaml, context
        )
        other_context = other_builder.get_result()

        assert context.commit == other_context.commit
        assert context.commit_report == other_context.commit_report
        assert context.bundle_analysis_report == other_context.bundle_analysis_report
        assert context.pull == other_context.pull
        with pytest.raises(ContextNotLoadedError):
            other_context.bundle_analysis_comparison

        fake_comparison = MagicMock(
            name="fake_comparison", percentage_delta=10.0, total_size_delta=10.0
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
