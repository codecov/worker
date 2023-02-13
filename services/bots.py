import logging
from typing import Dict, Optional, Tuple

from shared.config import get_config
from shared.torngit.base import TokenType

from database.models import Owner, Repository
from helpers.environment import is_enterprise
from helpers.exceptions import OwnerWithoutValidBotError, RepositoryWithoutValidBotError
from services.encryption import encryptor
from services.github import get_github_integration_token

log = logging.getLogger(__name__)


def get_repo_appropriate_bot_token(repo: Repository) -> Tuple[Dict, Optional[Owner]]:
    if repo.using_integration and repo.owner.integration_id:
        github_token = get_github_integration_token(
            repo.owner.service, repo.owner.integration_id
        )
        # The token is not owned by an Owner object, so 2nd arg is None
        return dict(key=github_token), None
    public_bot_dict = get_config(repo.service, "bot")
    tokenless_bot_dict = get_config(
        repo.service, "bots", "tokenless", default=public_bot_dict
    )
    if not repo.private or is_enterprise():
        if tokenless_bot_dict and tokenless_bot_dict.get("key"):
            log.info(
                "Using tokenless bot as bot fallback",
                extra=dict(
                    repoid=repo.repoid, botname=tokenless_bot_dict.get("username")
                ),
            )
            # Once again token not owned by an Owner.
            return tokenless_bot_dict, None
    return get_repo_particular_bot_token(repo)


def get_repo_particular_bot_token(repo) -> Tuple[Dict, Owner]:
    appropriate_bot = _get_repo_appropriate_bot(repo)
    token_dict = encryptor.decrypt_token(appropriate_bot.oauth_token)
    token_dict["username"] = appropriate_bot.username
    return token_dict, appropriate_bot


def get_token_type_mapping(repo: Repository):
    if repo.private:
        return None
    if repo.using_integration and repo.owner.integration_id:
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


def get_owner_appropriate_bot_token(owner, using_integration) -> Dict:
    if owner.integration_id and using_integration:
        github_token = get_github_integration_token(owner.service, owner.integration_id)
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
