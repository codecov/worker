from shared.config import get_config
from shared.torngit.base import TokenType
from shared.typings.oauth_token_types import Token

from services.github import get_github_integration_token


def get_dedicated_app_token_from_config(
    service: str, token_type: TokenType
) -> Token | None:
    # GitHub can have 'dedicated_apps', and those are preferred
    dedicated_app = get_config(service, "dedicated_apps", token_type.value, default={})
    app_id = dedicated_app.get("id")
    installation_id = dedicated_app.get("installation_id")
    pem_exists = "pem" in dedicated_app
    if app_id and installation_id and pem_exists:
        actual_token = get_github_integration_token(
            service,
            app_id=app_id,
            installation_id=installation_id,
            pem_path=f"yaml+file://{service}.dedicated_apps.{token_type.value}",
        )
        return Token(key=actual_token, username=f"{token_type.value}_dedicated_app")


def get_token_type_from_config(service: str, token_type: TokenType) -> Token | None:
    if service in ["github", "github_enterprise"]:
        dedicated_app_config = get_dedicated_app_token_from_config(service, token_type)
        if dedicated_app_config:
            return dedicated_app_config

    return get_config(service, "bots", token_type.value)
