from unittest.mock import AsyncMock, MagicMock

import pytest
from shared.yaml import UserYaml

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.tests.factories.core import CommitFactory
from services.bundle_analysis.new_notify import (
    BundleAnalysisNotifyReturn,
    BundleAnalysisNotifyService,
    NotificationFullContext,
    NotificationSuccess,
)
from services.bundle_analysis.new_notify.conftest import (
    get_commit_pair,
    get_report_pair,
    save_mock_bundle_analysis_report,
)
from services.bundle_analysis.new_notify.contexts import (
    BaseBundleAnalysisNotificationContext,
    NotificationContextBuildError,
)
from services.bundle_analysis.new_notify.types import NotificationType
from services.notification.notifiers.base import NotificationResult


def override_comment_builder_and_message_strategy(mocker):
    mock_comment_builder = MagicMock(name="fake_builder")
    mock_comment_builder.get_result.return_value = "D. Context"
    mock_comment_builder.build_context.return_value = mock_comment_builder
    mock_comment_builder.initialize_from_context.return_value = mock_comment_builder
    mock_comment_builder = mocker.patch(
        "services.bundle_analysis.new_notify.BundleAnalysisPRCommentContextBuilder",
        return_value=mock_comment_builder,
    )
    mock_markdown_strategy = AsyncMock(name="fake_markdown_strategy")
    mock_markdown_strategy = mocker.patch(
        "services.bundle_analysis.new_notify.BundleAnalysisCommentMarkdownStrategy",
        return_value=mock_markdown_strategy,
    )
    return (mock_comment_builder, mock_markdown_strategy)


@pytest.fixture
def mock_base_context():
    context_requirements = (
        CommitFactory(),
        UserYaml.from_dict({}),
        GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    )
    context = BaseBundleAnalysisNotificationContext(*context_requirements)
    context.commit_report = MagicMock(name="fake_CommitReport")
    context.bundle_analysis_report = MagicMock(name="fake_BundleAnalysisReport")
    return context


class TestCreateContextForNotification:
    def test_build_base_context(self, mocker, dbsession, mock_storage):
        head_commit, base_commit = get_commit_pair(dbsession)
        head_commit_report, _ = get_report_pair(dbsession, (head_commit, base_commit))
        save_mock_bundle_analysis_report(
            head_commit.repository,
            head_commit_report,
            mock_storage,
            sample_report_number=1,
        )
        service = BundleAnalysisNotifyService(head_commit, UserYaml.from_dict({}))
        base_context = service.build_base_context()
        assert base_context.commit_report == head_commit_report
        assert base_context.bundle_analysis_report.session_count() == 19

    def test_create_context_success(self, mock_base_context, mocker):
        mock_comment_builder, mock_markdown_strategy = (
            override_comment_builder_and_message_strategy(mocker)
        )
        service = BundleAnalysisNotifyService(
            mock_base_context.commit, mock_base_context.current_yaml
        )
        mock_markdown_strategy.return_value = "D. Strategy"
        result = service.create_context_for_notification(
            mock_base_context, NotificationType.PR_COMMENT
        )
        assert result == NotificationFullContext("D. Context", "D. Strategy")
        mock_comment_builder.return_value.build_context.assert_called()
        mock_comment_builder.return_value.get_result.assert_called()

    @pytest.mark.parametrize(
        "unknown_notification",
        [
            NotificationType.COMMIT_STATUS,
            NotificationType.GITHUB_COMMIT_CHECK,
        ],
    )
    def test_create_contexts_unknown_notification(
        self, mock_base_context, unknown_notification
    ):
        service = BundleAnalysisNotifyService(
            mock_base_context.commit, mock_base_context.current_yaml
        )
        assert (
            service.create_context_for_notification(
                mock_base_context, unknown_notification
            )
            is None
        )

    def test_create_context_for_notification_build_fails(
        self, mocker, mock_base_context
    ):
        mock_comment_builder = MagicMock(name="fake_builder")
        mock_comment_builder.initialize_from_context.return_value = mock_comment_builder
        mock_comment_builder.build_context.side_effect = NotificationContextBuildError(
            "mock_failed_step"
        )
        mock_comment_builder = mocker.patch(
            "services.bundle_analysis.new_notify.BundleAnalysisPRCommentContextBuilder",
            return_value=mock_comment_builder,
        )
        service = BundleAnalysisNotifyService(
            mock_base_context.commit, mock_base_context.current_yaml
        )
        assert (
            service.create_context_for_notification(
                mock_base_context, NotificationType.PR_COMMENT
            )
            is None
        )


class TestBundleAnalysisNotifyService:
    def test_skip_all_notification_base_context_failed(
        self, mocker, dbsession, mock_storage, caplog
    ):
        head_commit, _ = get_commit_pair(dbsession)
        service = BundleAnalysisNotifyService(
            head_commit,
            UserYaml.from_dict({"comment": {"require_bundle_changes": False}}),
        )
        result = service.notify()
        error_logs = [
            record for record in caplog.records if record.levelname == "ERROR"
        ]
        warning_logs = [
            record for record in caplog.records if record.levelname == "WARNING"
        ]
        assert any(
            error.message == "Failed to build NotificationContext"
            for error in error_logs
        )
        assert any(
            warning.message
            == "Skipping ALL notifications because there's no base context"
            for warning in warning_logs
        )
        assert result == BundleAnalysisNotifyReturn(
            notifications_configured=(
                NotificationType.COMMIT_STATUS,
                NotificationType.PR_COMMENT,
            ),
            notifications_successful=tuple(),
        )

    @pytest.mark.parametrize(
        "current_yaml, expected_configured_count, expected_success_count",
        [
            pytest.param(
                {"comment": {"require_bundle_changes": False}},
                2,
                1,
                id="only_comment_sent",
            )
        ],
    )
    def test_notify(
        self,
        current_yaml,
        expected_configured_count,
        expected_success_count,
        mocker,
        mock_base_context,
    ):
        mock_comment_builder, mock_markdown_strategy = (
            override_comment_builder_and_message_strategy(mocker)
        )
        mock_comment_builder.return_value.get_result.return_value = MagicMock(
            name="fake_context", notification_type=NotificationType.PR_COMMENT
        )
        mock_markdown_strategy.build_message.return_value = "D. Message"
        mock_markdown_strategy.send_message.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            github_app_used=None,
        )
        mocker.patch.object(
            BundleAnalysisNotifyService,
            "build_base_context",
            return_value=mock_base_context,
        )
        current_yaml = UserYaml.from_dict(current_yaml)
        mock_base_context.current_yaml = current_yaml
        service = BundleAnalysisNotifyService(mock_base_context.commit, current_yaml)
        result = service.notify()
        assert result == BundleAnalysisNotifyReturn(
            notifications_configured=(
                NotificationType.COMMIT_STATUS,
                NotificationType.PR_COMMENT,
            ),
            notifications_successful=(NotificationType.PR_COMMENT,),
        )
        assert len(result.notifications_configured) == expected_configured_count
        assert len(result.notifications_successful) == expected_success_count

    @pytest.mark.parametrize(
        "result, success_value",
        [
            (BundleAnalysisNotifyReturn([], []), NotificationSuccess.NOTHING_TO_NOTIFY),
            (
                BundleAnalysisNotifyReturn(
                    [NotificationType.COMMIT_STATUS], [NotificationType.COMMIT_STATUS]
                ),
                NotificationSuccess.FULL_SUCCESS,
            ),
            (
                BundleAnalysisNotifyReturn(
                    [NotificationType.COMMIT_STATUS, NotificationType.PR_COMMENT],
                    [NotificationType.COMMIT_STATUS],
                ),
                NotificationSuccess.PARTIAL_SUCCESS,
            ),
        ],
    )
    def test_to_NotificationSuccess(self, result, success_value):
        assert result.to_NotificationSuccess() == success_value
