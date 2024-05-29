import logging

from shared.django_apps.codecov_auth.models import Owner, Service
from shared.typings.torngit import GithubInstallationInfo

from helpers.exceptions import OwnerWithoutValidBotError
from services.bots_django.github_apps import get_github_app_token
from services.bots_django.types import TokenWithOwner
from services.encryption import encryptor

log = logging.getLogger(__name__)


def get_owner_or_appropriate_bot(owner: Owner, repoid: int | None = None) -> Owner:
    if owner.bot is not None and owner.bot.oauth_token is not None:
        log.info(
            "Owner has specific bot",
            extra=dict(botid=owner.bot.ownerid, ownerid=owner.ownerid, repoid=repoid),
        )
        return owner.bot
    elif owner.oauth_token is not None:
        log.info(
            "No bot, using owner", extra=dict(ownerid=owner.ownerid, repoid=repoid)
        )
        return owner
    raise OwnerWithoutValidBotError()


def get_owner_appropriate_bot_token(
    owner, installation_info: GithubInstallationInfo | None = None
) -> TokenWithOwner:
    if installation_info:
        result = get_github_app_token(Service(owner.service), installation_info)
        return result

    token_owner = get_owner_or_appropriate_bot(owner)
    return encryptor.decrypt_token(token_owner.oauth_token), token_owner
