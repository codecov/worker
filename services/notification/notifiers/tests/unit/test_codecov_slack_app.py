from unittest.mock import patch
from services.notification.notifiers.codecov_slack_app import CodecovSlackAppNotifier
from database.enums import Notification
import pytest

class TestCodecovSlackAppNotifier(object):
    def test_is_enabled(self, dbsession, mock_configuration, sample_comparison):
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        assert notifier.is_enabled() == True

    def test_notification_type(self, dbsession, mock_configuration, sample_comparison):
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        assert notifier.notification_type == Notification.codecov_slack_app

    @patch("requests.post")
    @pytest.mark.asyncio
    async def test_notify(self, mock_requests_post, dbsession, mock_configuration, sample_comparison):
        mock_requests_post.return_value.status_code = 200
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation == "Successfully notified slack app"

    
    @patch("requests.post")
    @pytest.mark.asyncio
    async def test_notify_failure(self, mock_requests_post, dbsession, mock_configuration, sample_comparison):
        mock_requests_post.return_value.status_code = 500
        mock_requests_post.return_value.reason = "Internal Server Error"
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison)
        assert result.notification_successful == False
        assert result.explanation == "Failed to notify slack app\nError 500: Internal Server Error."
