import logging
from typing import Dict, Optional

from shared.config import get_config
from shared.django_apps.codecov_auth.models import Service
from shared.torngit.base import TokenType
from shared.typings.oauth_token_types import Token
from shared.typings.torngit import GithubInstallationInfo

from database.models import Owner, Repository
from helpers.environment import is_enterprise
from helpers.exceptions import (
    OwnerWithoutValidBotError,
    RepositoryWithoutValidBotError,
)
from services.bots.github_apps import get_github_app_token
from services.bots.tokenless import get_public_bot_token
from services.bots.types import TokenTypeMapping, TokenWithOwner
from services.encryption import encryptor

log = logging.getLogger(__name__)


def get_repo_appropriate_bot_token(
    repo: Repository,
    installation_info: Optional[Dict] = None,
) -> TokenWithOwner:
    log.info(
        "Get repo appropriate bot token",
        extra=dict(
            installation_info=installation_info,
            repoid=repo.repoid,
            service=repo.service,
        ),
    )

    service = Service(repo.service)

    if is_enterprise() and get_config(repo.service, "bot"):
        return get_public_bot_token(service, repo.repoid)

    if installation_info:
        return get_github_app_token(service, installation_info)
    try:
        token_dict, appropriate_bot = get_repo_particular_bot_token(repo)
        return token_dict, appropriate_bot
    except RepositoryWithoutValidBotError as e:
        if not repo.private:
            return get_public_bot_token(service, repo.repoid)
        raise e


def get_repo_particular_bot_token(repo) -> TokenWithOwner:
    appropriate_bot = _get_repo_appropriate_bot(repo)
    token_dict = encryptor.decrypt_token(appropriate_bot.oauth_token)
    token_dict["username"] = appropriate_bot.username
    return token_dict, appropriate_bot


def get_token_type_mapping(repo: Repository) -> TokenTypeMapping | None:
    """Gets the fallback tokens configured via install YAML per function.

    This only affects _public_ repos, as private ones need a token defined.
    A public repo might have a token defined (the admin_bot), in which case it is used for all functions,
    except comment.
    """
    if repo.private:
        return None

    admin_bot = None
    try:
        admin_bot, _ = get_repo_particular_bot_token(repo)
    except RepositoryWithoutValidBotError:
        log.warning(
            "Repository has no good bot for admin, but still continuing operations in case it is not doing an admin call anyway",
            extra=dict(repoid=repo.repoid),
        )
    return {
        TokenType.read: admin_bot or get_config(repo.service, "bots", "read"),
        TokenType.admin: admin_bot,
        TokenType.comment: get_config(repo.service, "bots", "comment"),
        TokenType.status: admin_bot or get_config(repo.service, "bots", "status"),
        TokenType.tokenless: admin_bot or get_config(repo.service, "bots", "tokenless"),
    }


def _get_repo_appropriate_bot(repo: Repository) -> Owner:
    if repo.bot is not None and repo.bot.oauth_token is not None:
        log.info(
            "Repo has specific bot",
            extra=dict(repoid=repo.repoid, botid=repo.bot.ownerid),
        )
        return repo.bot
    if repo.owner.bot is not None and repo.owner.bot.oauth_token is not None:
        log.info(
            "Repo Owner has specific bot",
            extra=dict(
                repoid=repo.repoid,
                botid=repo.owner.bot.ownerid,
                ownerid=repo.owner.ownerid,
            ),
        )
        return repo.owner.bot
    if repo.owner.oauth_token is not None:
        log.info(
            "Using repo owner as bot fallback",
            extra=dict(repoid=repo.repoid, ownerid=repo.owner.ownerid),
        )
        return repo.owner
    raise RepositoryWithoutValidBotError()


def get_owner_appropriate_bot_token(
    owner, installation_info: GithubInstallationInfo | None = None
) -> Token:
    if installation_info:
        result = get_github_app_token(Service(owner.service), installation_info)
        return result[0]

    return encryptor.decrypt_token(_get_owner_or_appropriate_bot(owner).oauth_token)


def _get_owner_or_appropriate_bot(owner: Owner) -> Owner:
    if owner.bot is not None and owner.bot.oauth_token is not None:
        log.info(
            "Owner has specific bot",
            extra=dict(botid=owner.bot.ownerid, ownerid=owner.ownerid),
        )
        return owner.bot
    elif owner.oauth_token is not None:
        log.info("No bot, using owner", extra=dict(ownerid=owner.ownerid))
        return owner
    raise OwnerWithoutValidBotError()
