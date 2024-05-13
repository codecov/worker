import logging

from shared.config import get_config
from shared.django_apps.codecov_auth.models import Service

from helpers.exceptions import RepositoryWithoutValidBotError
from services.bots.types import TokenWithOwner

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
