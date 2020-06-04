import logging

from database.models import Repository, Owner
from services.github import get_github_integration_token
from services.encryption import encryptor
from helpers.exceptions import RepositoryWithoutValidBotError, OwnerWithoutValidBotError
from shared.torngit.base import TokenType
from shared.config import get_config
from typing import Any, Dict

log = logging.getLogger(__name__)


def get_repo_appropriate_bot_token(repo: Repository) -> Dict:
    if repo.using_integration and repo.owner.integration_id:
        github_token = get_github_integration_token(
            repo.owner.service, repo.owner.integration_id
        )
        return dict(key=github_token)
    if not repo.private:
        public_bot_dict = get_config(repo.service, "bot")
        if public_bot_dict and public_bot_dict.get("key"):
            log.info(
                "Using default bot since repo is public",
                extra=dict(repoid=repo.repoid, botname=public_bot_dict.get("username")),
            )
            return public_bot_dict
    return get_repo_particular_bot(repo)


def get_repo_particular_bot(repo):
    appropriate_bot = _get_repo_appropriate_bot(repo)
    token_dict = encryptor.decrypt_token(appropriate_bot.oauth_token)
    token_dict["username"] = appropriate_bot.username
    return token_dict


def get_token_type_mapping(repo: Repository):
    if repo.private:
        return None
    if repo.using_integration and repo.owner.integration_id:
        return None
    return {
        TokenType.read: get_config(repo.service, "bots", "read"),
        TokenType.admin: get_repo_particular_bot(repo),
        TokenType.comment: get_config(repo.service, "bots", "comment"),
        TokenType.status: get_config(repo.service, "bots", "status"),
    }


def _get_repo_appropriate_bot(repo):
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
    if owner.integration_id:
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
