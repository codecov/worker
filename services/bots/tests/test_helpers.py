from unittest.mock import patch

from shared.torngit.base import TokenType
from shared.typings.oauth_token_types import Token

from services.bots.helpers import (
    get_dedicated_app_token_from_config,
    get_token_type_from_config,
)


@patch("services.bots.helpers.get_github_integration_token")
def test_get_dedicated_app_token_from_config(
    mock_get_integration_token, mock_configuration
):
    mock_configuration.set_params(
        {
            "github": {
                "dedicated_apps": {
                    "read": {"id": 1234, "installation_id": 1000, "pem": "some_path"},
                    "commit": {
                        "id": 2345,
                        "installation_id": 1000,
                        "pem": "another_path",
                    },
                    "tokenless": {"id": 1111},  # not configured (missing pem)
                },
            }
        }
    )
    mock_get_integration_token.return_value = "installation_access_token"
    # TokenType.read has a dedicated app
    assert get_dedicated_app_token_from_config("github", TokenType.read) == Token(
        key="installation_access_token", username="read_dedicated_app"
    )
    mock_get_integration_token.assert_called_with(
        "github",
        app_id=1234,
        installation_id=1000,
        pem_path="yaml+file://github.dedicated_apps.read",
    )
    # TokenType.commit has a different dedicated app
    assert get_dedicated_app_token_from_config("github", TokenType.commit) == Token(
        key="installation_access_token", username="commit_dedicated_app"
    )
    mock_get_integration_token.assert_called_with(
        "github",
        app_id=2345,
        installation_id=1000,
        pem_path="yaml+file://github.dedicated_apps.commit",
    )
    # TokenType.pull has no dedicated app
    assert get_dedicated_app_token_from_config("github", TokenType.pull) is None
    assert mock_get_integration_token.call_count == 2  # no new calls
    # TokenType.tokenless is not properly configured
    assert get_dedicated_app_token_from_config("github", TokenType.tokenless) is None
    assert mock_get_integration_token.call_count == 2  # no new calls


@patch("services.bots.helpers.get_github_integration_token")
def test_get_token_type_from_config(mock_get_integration_token, mock_configuration):
    mock_configuration.set_params(
        {
            "github": {
                "bots": {
                    "tokenless": {"key": "bot_token", "username": "tokenless_bot"},
                    "read": {"key": "bot_token", "username": "read_bot"},
                },
                "dedicated_apps": {
                    "read": {"id": 1234, "installation_id": 1000, "pem": "some_path"},
                    "commit": {
                        "id": 2345,
                        "installation_id": 1000,
                        "pem": "another_path",
                    },
                    "tokenless": {"id": 1111},  # not configured (missing pem)
                },
            }
        }
    )
    mock_get_integration_token.return_value = "installation_access_token"
    # TokenType.read has a dedicated app AND bot.
    # Dedicated app is preferred.
    assert get_token_type_from_config("github", TokenType.read) == Token(
        key="installation_access_token", username="read_dedicated_app"
    )
    # TokenType.pull has no dedicated app AND no bot
    assert get_token_type_from_config("github", TokenType.pull) is None
    # TokenType.tokenless is not properly configured BUT has dedicated bot
    assert get_token_type_from_config("github", TokenType.tokenless) == Token(
        key="bot_token", username="tokenless_bot"
    )


@patch("services.bots.helpers.get_github_integration_token")
def test_get_token_type_from_config_not_github_skip_dedicated_apps(
    mock_get_integration_token, mock_configuration
):
    mock_configuration.set_params(
        {
            "gitlab": {
                "bots": {
                    "read": {"key": "bot_token", "username": "read_bot"},
                },
            },
            "github": {
                "dedicated_apps": {
                    "read": {"id": 1234, "pem": "some_path"},
                },
            },
        }
    )
    assert get_token_type_from_config("gitlab", TokenType.read) == Token(
        key="bot_token", username="read_bot"
    )
    mock_get_integration_token.assert_not_called()
