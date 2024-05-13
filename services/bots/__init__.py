import logging
from typing import Dict, List, Optional

from shared.config import get_config
from shared.django_apps.codecov_auth.models import Service
from shared.torngit.base import TokenType
from shared.typings.torngit import GithubInstallationInfo

from database.models import Owner, Repository
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from helpers.environment import is_enterprise
from helpers.exceptions import (
    OwnerWithoutValidBotError,
    RepositoryWithoutValidBotError,
)
from services.bots.github_apps import (
    get_github_app_info_for_owner,
    get_github_app_token,
)
from services.bots.tokenless import get_public_bot_token
from services.bots.types import (
    AdapterAuthInformation,
    TokenTypeMapping,
    TokenWithOwner,
)
from services.encryption import encryptor

log = logging.getLogger(__name__)


def get_adapter_auth_information(
    owner: Owner,
    repository: Optional[Repository] = None,
    *,
    ignored_installations: bool = False,
    installation_name_to_use: str | None = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
) -> AdapterAuthInformation:
    """Gets all the auth information needed to send requests to the provider"""
    installation_info: GithubInstallationInfo | None = None
    token_type_mapping = None
    fallback_installations: List[GithubInstallationInfo] | None = None
    if (
        Service(owner.service) in [Service.GITHUB, Service.GITHUB_ENTERPRISE]
        # in sync_teams and sync_repos we might prefer to use the owner's OAuthToken instead of installation
        and not ignored_installations
    ):
        installations_available_info = get_github_app_info_for_owner(
            owner,
            repository=repository,
            installation_name=installation_name_to_use,
        )
        if installations_available_info != []:
            installation_info, *fallback_installations = installations_available_info

    if repository:
        token, token_owner = _get_repo_appropriate_bot_token(
            repository, installation_info
        )
    else:
        token, token_owner = _get_owner_appropriate_bot_token(owner, installation_info)
    if repository and installation_info is None:
        token_type_mapping = _get_token_type_mapping(repository)
    return AdapterAuthInformation(
        token=token,
        token_owner=token_owner,
        selected_installation_info=installation_info,
        fallback_installations=fallback_installations,
        token_type_mapping=token_type_mapping,
    )


def _get_repo_appropriate_bot_token(
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
        token_dict, appropriate_bot = _get_repo_particular_bot_token(repo)
        return token_dict, appropriate_bot
    except RepositoryWithoutValidBotError as e:
        if not repo.private:
            return get_public_bot_token(service, repo.repoid)
        raise e


def _get_repo_particular_bot_token(repo) -> TokenWithOwner:
    appropriate_bot = _get_repo_appropriate_bot(repo)
    token_dict = encryptor.decrypt_token(appropriate_bot.oauth_token)
    token_dict["username"] = appropriate_bot.username
    return token_dict, appropriate_bot


def _get_token_type_mapping(repo: Repository) -> TokenTypeMapping | None:
    """Gets the fallback tokens configured via install YAML per function.

    This only affects _public_ repos, as private ones need a token defined.
    A public repo might have a token defined (the admin_bot), in which case it is used for all functions,
    except comment.
    """
    if repo.private:
        return None

    admin_bot = None
    try:
        admin_bot, _ = _get_repo_particular_bot_token(repo)
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
    try:
        return _get_owner_or_appropriate_bot(repo.owner)
    except OwnerWithoutValidBotError:
        raise RepositoryWithoutValidBotError()


def _get_owner_appropriate_bot_token(
    owner, installation_info: GithubInstallationInfo | None = None
) -> TokenWithOwner:
    if installation_info:
        result = get_github_app_token(Service(owner.service), installation_info)
        return result

    token_owner = _get_owner_or_appropriate_bot(owner)
    return encryptor.decrypt_token(token_owner.oauth_token), token_owner


def _get_owner_or_appropriate_bot(owner: Owner, repoid: int | None = None) -> Owner:
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
