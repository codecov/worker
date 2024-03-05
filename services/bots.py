import logging
from random import shuffle
from typing import Dict, Optional, Tuple

from shared.config import get_config
from shared.torngit.base import TokenType

from database.models import Owner, Repository
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from helpers.environment import is_enterprise
from helpers.exceptions import OwnerWithoutValidBotError, RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from services.encryption import encryptor
from services.github import get_github_integration_token

log = logging.getLogger(__name__)


def get_owner_installation_id(
    owner: Owner,
    deprecated_using_integration: bool,
    *,
    repository: Optional[Repository] = None,
    installation_name: str = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    # This is used for SyncTeams and SyncRepos if we are not
    # using the installations to list these values
    # We have this secondary value because `deprecated_using_integration` is... deprecated
    # And might get out-of-sync soon
    ignore_installation: bool = False
) -> Optional[Dict]:

    if not ignore_installation or deprecated_using_integration:
        default_app_installation_filter = list(
            filter(
                lambda obj: obj.name == installation_name and obj.is_configured(),
                owner.github_app_installations or [],
            )
        )
        # We shuffle the results so apps are considered with close to the same probability
        # (so that if the owner has multiple apps for the same objective their rate limit
        # is spent equally fast)
        shuffle(default_app_installation_filter)
        # filter is an Iterator, so we need to scan matches
        for app_installation in default_app_installation_filter:
            if repository:
                if app_installation.is_repo_covered_by_integration(repository):
                    log.info(
                        "Selected github installation for repo",
                        extra=dict(
                            installation=app_installation.external_id,
                            installation_name=app_installation.name,
                        ),
                    )
                    return {
                        "installation_id": app_installation.installation_id,
                        "app_id": app_installation.app_id,
                        "pem_path": app_installation.pem_path,
                    }
                # Not returning None here because we found situations where ghapp installations will mark the
                # the repo as NOT covered but it is, in fact, covered.
                # We need to backfill some things.
            else:
                # Getting owner installation - not tied to any particular repo
                log.info(
                    "Selected github installation for owner",
                    extra=dict(
                        installation=app_installation.external_id,
                        installation_name=app_installation.name,
                    ),
                )
                return {
                    "installation_id": app_installation.installation_id,
                    "app_id": app_installation.app_id,
                    "pem_path": app_installation.pem_path,
                }
    # DEPRECATED FLOW - begin
    if owner.integration_id and deprecated_using_integration:
        log.info("Selected owner integration to communicate with github")
        return {"installation_id": owner.integration_id}
    # DEPRECATED FLOW - end
    return None


def get_repo_appropriate_bot_token(
    repo: Repository,
    installation_name_to_use: Optional[str] = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
) -> Tuple[Dict, Optional[Owner]]:
    if is_enterprise() and get_config(repo.service, "bot"):
        return get_public_bot_token(repo)

    installation_dict = get_owner_installation_id(
        repo.owner,
        repo.using_integration,
        repository=repo,
        ignore_installation=False,
        installation_name=installation_name_to_use,
    )
    if installation_dict:
        github_token = get_github_integration_token(
            repo.owner.service,
            installation_dict["installation_id"],
            app_id=installation_dict.get("app_id", None),
            pem_path=installation_dict.get("pem_path", None),
        )
        installation_token = dict(key=github_token)
        # The token is not owned by an Owner object, so 2nd arg is None
        return installation_token, None
    try:
        token_dict, appropriate_bot = get_repo_particular_bot_token(repo)
        return token_dict, appropriate_bot
    except RepositoryWithoutValidBotError as e:
        if not repo.private:
            return get_public_bot_token(repo)
        raise e


def get_public_bot_token(repo):
    public_bot_dict = get_config(repo.service, "bot")
    tokenless_bot_dict = get_config(
        repo.service, "bots", "tokenless", default=public_bot_dict
    )
    if tokenless_bot_dict and tokenless_bot_dict.get("key"):
        log.info(
            "Using tokenless bot as bot fallback",
            extra=dict(repoid=repo.repoid, botname=tokenless_bot_dict.get("username")),
        )
        # Once again token not owned by an Owner.
        return tokenless_bot_dict, None


def get_repo_particular_bot_token(repo) -> Tuple[Dict, Owner]:
    appropriate_bot = _get_repo_appropriate_bot(repo)
    token_dict = encryptor.decrypt_token(appropriate_bot.oauth_token)
    token_dict["username"] = appropriate_bot.username
    return token_dict, appropriate_bot


def get_token_type_mapping(
    repo: Repository, installation_name: str = GITHUB_APP_INSTALLATION_DEFAULT_NAME
):
    if repo.private:
        return None
    installation_dict = get_owner_installation_id(
        repo.owner,
        repo.using_integration,
        repository=repo,
        ignore_installation=False,
        installation_name=installation_name,
    )
    if installation_dict:
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
    owner, using_integration, ignore_installation: bool = False
) -> Dict:
    installation_dict = get_owner_installation_id(
        owner, using_integration, ignore_installation=ignore_installation
    )
    if installation_dict:
        github_token = get_github_integration_token(
            owner.service,
            installation_dict["installation_id"],
            app_id=installation_dict.get("app_id", None),
            pem_path=installation_dict.get("pem_path", None),
        )
        return dict(key=github_token)

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
