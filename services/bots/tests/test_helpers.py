from unittest.mock import patch

import pytest
from shared.torngit.base import TokenType
from shared.typings.oauth_token_types import Token

from services.bots.helpers import (
    get_dedicated_app_token_from_config,
    get_token_type_from_config,
)


@pytest.fixture
def mock_configuration(mock_configuration):
    custom_params = {
        "gitlab": {
            "bots": {
                "read": {"key": "bot_token", "username": "read_bot"},
            },
        },
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
        },
    }
    mock_configuration.set_params(custom_params)
    return custom_params


@pytest.mark.parametrize(
    "token_type",
    [
        # Has a dedicated app that is configured
        pytest.param(TokenType.read, id="TokenType.read-app_configured"),
        # Has a _different_ dedicated app that is configured
        pytest.param(TokenType.commit, id="TokenType.commit-app_configured"),
    ],
)
@patch("services.bots.helpers.get_github_integration_token")
def test_get_dedicated_app_token_from_config(
    mock_get_integration_token, token_type, mock_configuration
):
    mock_get_integration_token.return_value = "installation_access_token"
    dedicated_app_details = mock_configuration["github"]["dedicated_apps"][
        token_type.value
    ]

    assert get_dedicated_app_token_from_config("github", token_type) == Token(
        key="installation_access_token", username=f"{token_type.value}_dedicated_app"
    )
    mock_get_integration_token.assert_called_with(
        "github",
        app_id=dedicated_app_details["id"],
        installation_id=dedicated_app_details["installation_id"],
        pem_path=f"yaml+file://github.dedicated_apps.{token_type.value}",
    )


@pytest.mark.parametrize(
    "token_type",
    [
        # No configuration present
        pytest.param(TokenType.pull, id="TokenType.pull-app_NOT_configured"),
        # Some configuration exist, but it's not properly configured, so we can't use
        pytest.param(
            TokenType.tokenless,
            id="TokenType.tokenless-app_NOT_properly_configured",
        ),
    ],
)
@patch("services.bots.helpers.get_github_integration_token")
def test_get_dedicated_app_token_from_config_not_configured(
    mock_get_integration_token, token_type, mock_configuration
):
    assert get_dedicated_app_token_from_config("github", token_type) is None
    mock_get_integration_token.assert_not_called()


@pytest.mark.parametrize(
    "token_type, expected",
    [
        pytest.param(
            TokenType.read,
            Token(key="installation_access_token", username="read_dedicated_app"),
            id="dedicated_app_AND_bot_configured",
        ),
        pytest.param(TokenType.pull, None, id="no_dedicated_app_no_bot"),
        pytest.param(
            TokenType.tokenless,
            Token(key="bot_token", username="tokenless_bot"),
            id="no_dedicated_app_yes_bot",
        ),
    ],
)
@patch("services.bots.helpers.get_github_integration_token")
def test_get_token_type_from_config(
    mock_get_integration_token, token_type, expected, mock_configuration
):
    mock_get_integration_token.return_value = "installation_access_token"
    assert get_token_type_from_config("github", token_type) == expected


@patch("services.bots.helpers.get_github_integration_token")
def test_get_token_type_from_config_not_github_skip_dedicated_apps(
    mock_get_integration_token, mock_configuration
):
    assert get_token_type_from_config("gitlab", TokenType.read) == Token(
        key="bot_token", username="read_bot"
    )
    mock_get_integration_token.assert_not_called()
