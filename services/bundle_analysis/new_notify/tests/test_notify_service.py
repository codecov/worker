from unittest.mock import MagicMock

import pytest
from shared.yaml import UserYaml

from database.tests.factories.core import CommitFactory
from services.bundle_analysis.new_notify import (
    BundleAnalysisNotifyReturn,
    BundleAnalysisNotifyService,
    NotificationFullContext,
    create_context_for_notification,
)
from services.bundle_analysis.new_notify.contexts import NotificationContextBuildError
from services.bundle_analysis.new_notify.types import NotificationType
from services.notification.notifiers.base import NotificationResult


def override_comment_builder_and_message_strategy(mocker):
    mock_comment_builder = MagicMock(name="fake_builder")
    mock_comment_builder.get_result.return_value = "D. Context"
    mock_comment_builder.build_context.return_value = mock_comment_builder
    mock_comment_builder.return_value.get_result.return_value = "D. Context"
    mock_comment_builder = mocker.patch(
        "services.bundle_analysis.new_notify.BundleAnalysisCommentContextBuilder",
        return_value=mock_comment_builder,
    )
    mock_markdown_strategy = MagicMock(name="fake_markdown_strategy")
    mock_markdown_strategy = mocker.patch(
        "services.bundle_analysis.new_notify.BundleAnalysisCommentMarkdownStrategy",
        return_value=mock_markdown_strategy,
    )
    return (mock_comment_builder, mock_markdown_strategy)


class TestCreateContextForNotification:
    def test_create_context_success(self, mocker):
        mock_comment_builder, mock_markdown_strategy = (
            override_comment_builder_and_message_strategy(mocker)
        )
        mock_markdown_strategy.return_value = "D. Strategy"
        result = create_context_for_notification(NotificationType.PR_COMMENT)
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
    def test_create_contexts_unknown_notification(self, unknown_notification):
        assert create_context_for_notification(unknown_notification) is None

    def test_create_context_for_notification_build_fails(self, mocker):
        mock_comment_builder = MagicMock(name="fake_builder")
        mock_comment_builder.build_context.side_effect = NotificationContextBuildError(
            "mock_failed_step"
        )
        mock_comment_builder = mocker.patch(
            "services.bundle_analysis.new_notify.BundleAnalysisCommentContextBuilder",
            return_value=mock_comment_builder,
        )
        assert create_context_for_notification(NotificationType.PR_COMMENT) is None


class TestBundleAnalysisNotifyService:
    @pytest.mark.parametrize(
        "current_yaml, expected_configured_count, expected_success_count",
        [
            pytest.param(
                {"comment": {"require_bundle_changes": False}}, 2, 1, id="only_comment"
            )
        ],
    )
    def test_notify(
        self, current_yaml, expected_configured_count, expected_success_count, mocker
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
        commit = CommitFactory(repository__owner__service="github")
        user_yaml = UserYaml.from_dict(current_yaml)
        service = BundleAnalysisNotifyService(commit, user_yaml)
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
