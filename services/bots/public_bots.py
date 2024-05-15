import logging

from shared.config import get_config
from shared.django_apps.codecov_auth.models import Service
from shared.torngit.base import TokenType
from shared.typings.oauth_token_types import Token

from database.models.core import Repository
from helpers.exceptions import RepositoryWithoutValidBotError
from services.bots.types import TokenTypeMapping, TokenWithOwner

log = logging.getLogger(__name__)


def get_public_bot_token(service: Service, repoid: int) -> TokenWithOwner:
    """Gets the configured public bot for a service.

    These bots are declared in the install YAML per service.
    They can only access public repositories (in general)
    """
    # Generic bot for this service
    public_bot_dict = get_config(service.value, "bot")
    # Function-specific bots for this service
    # In this case we want the 'tokenless' function
    tokenless_bot_dict = get_config(
        service.value, "bots", "tokenless", default=public_bot_dict
    )

    if tokenless_bot_dict and tokenless_bot_dict.get("key"):
        log.info(
            "Using tokenless bot as bot fallback",
            extra=dict(repoid=repoid, botname=tokenless_bot_dict.get("username")),
        )
        # Once again token not owned by an Owner.
        return tokenless_bot_dict, None

    log.error(
        "No tokenless bot dict in get_public_bot_token",
        extra=dict(repoid=repoid),
    )
    raise RepositoryWithoutValidBotError()


def get_token_type_mapping(
    repo: Repository, admin_bot_token: Token | None = None
) -> TokenTypeMapping | None:
    """Gets the fallback tokens configured via install YAML per function.

    This only affects _public_ repos, as private ones need a token defined.
    A public repo might have a token defined (the admin_bot), in which case it is used for all functions,
    except comment.
    """
    if repo.private:
        return None

    if admin_bot_token is None:
        log.warning(
            "No admin_bog_token provided, but still continuing operations in case it is not doing an admin call anyway",
            extra=dict(repoid=repo.repoid),
        )
    return {
        TokenType.read: admin_bot_token or get_config(repo.service, "bots", "read"),
        TokenType.admin: admin_bot_token,
        TokenType.comment: get_config(repo.service, "bots", "comment"),
        TokenType.status: admin_bot_token or get_config(repo.service, "bots", "status"),
        TokenType.tokenless: admin_bot_token
        or get_config(repo.service, "bots", "tokenless"),
    }
