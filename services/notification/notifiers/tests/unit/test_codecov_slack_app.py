from unittest.mock import patch

from database.enums import Notification
from services.notification.notifiers.codecov_slack_app import CodecovSlackAppNotifier


class TestCodecovSlackAppNotifier(object):
    def test_is_enabled(self, dbsession, mock_configuration, sample_comparison):
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"enabled": True},
            notifier_site_settings=True,
            current_yaml={"slack_app": {"enabled": True}},
            repository_service=None,
        )
        assert notifier.is_enabled() == True

    def test_is_enable_false(self, dbsession, mock_configuration, sample_comparison):
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"enabled": False},
            notifier_site_settings=True,
            current_yaml={"slack_app": {"enabled": False}},
            repository_service=None,
        )

        assert notifier.is_enabled() is False

    def test_notification_type(self, dbsession, mock_configuration, sample_comparison):
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"enabled": True},
            notifier_site_settings=True,
            current_yaml={"slack_app": {"enabled": True}},
            repository_service=None,
        )
        assert notifier.notification_type == Notification.codecov_slack_app

    @patch("requests.post")
    def test_notify(
        self, mock_requests_post, dbsession, mock_configuration, sample_comparison
    ):
        mock_requests_post.return_value.status_code = 200
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"enabled": True},
            notifier_site_settings=True,
            current_yaml={"slack_app": {"enabled": True}},
            repository_service=None,
        )
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation == "Successfully notified slack app"

    @patch("requests.post")
    def test_notify_failure(
        self, mock_requests_post, dbsession, mock_configuration, sample_comparison
    ):
        mock_requests_post.return_value.status_code = 500
        mock_requests_post.return_value.reason = "Internal Server Error"
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"enabled": True},
            notifier_site_settings=True,
            current_yaml={"slack_app": {"enabled": True}},
            repository_service=None,
        )
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == False
        assert (
            result.explanation
            == "Failed to notify slack app\nError 500: Internal Server Error."
        )

    @patch("requests.post")
    def test_notify_request_being_called(
        self, mock_requests_post, dbsession, mock_configuration, sample_comparison
    ):
        mock_requests_post.return_value.status_code = 200
        notifier = CodecovSlackAppNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"enabled": True},
            notifier_site_settings=True,
            current_yaml={"slack_app": {"enabled": True}},
            repository_service=None,
        )
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert mock_requests_post.call_count == 1
        assert mock_requests_post.is_called_with(
            {
                "repository": "sing-outside-letter",
                "owner": "test_notify",
                "comparison": {
                    "url": "https://app.codecov.io/gh/test_notify/sing-outside-letter/pull/24",
                    "message": "increased",
                    "coverage": "10.00",
                    "notation": "+",
                    "head_commit": {
                        "commitid": "936b768a1057bbe8371083ab4ec96a196ec730b6",
                        "branch": "new_branch",
                        "message": "Company here customer page by player threat.",
                        "author": "benjaminford",
                        "timestamp": "2019-02-01T17:59:47",
                        "ci_passed": True,
                        "totals": {
                            "C": 0,
                            "M": 0,
                            "N": 0,
                            "b": 0,
                            "c": "85.00000",
                            "d": 0,
                            "diff": [1, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                            "f": 3,
                            "h": 17,
                            "m": 3,
                            "n": 20,
                            "p": 0,
                            "s": 1,
                        },
                        "pull": 1,
                    },
                    "base_commit": {
                        "commitid": "db89f0ead214b647fe7eef9e1c42b78279e234bb",
                        "branch": None,
                        "message": "Morning loss contain impact old.",
                        "author": "stewartbrendan",
                        "timestamp": "2019-02-01T17:59:47",
                        "ci_passed": True,
                        "totals": {
                            "C": 0,
                            "M": 0,
                            "N": 0,
                            "b": 0,
                            "c": "85.00000",
                            "d": 0,
                            "diff": [1, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                            "f": 3,
                            "h": 17,
                            "m": 3,
                            "n": 20,
                            "p": 0,
                            "s": 1,
                        },
                        "pull": 1,
                    },
                    "head_totals_c": "60.00000",
                },
            }
        )
