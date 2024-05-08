import logging
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from shared.config import get_config
from shared.github import is_installation_rate_limited
from shared.torngit.base import TokenType
from shared.typings.torngit import GithubInstallationInfo

from database.models import Owner, Repository
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from helpers.environment import is_enterprise
from helpers.exceptions import (
    NoConfiguredAppsAvailable,
    OwnerWithoutValidBotError,
    RepositoryWithoutValidBotError,
)
from services.encryption import encryptor
from services.github import get_github_integration_token
from services.redis import get_redis_connection

log = logging.getLogger(__name__)


MAX_GITHUB_APP_SELECTION_WEIGHT = 1200


def _get_installation_weight(installation: GithubAppInstallation) -> int:
    """The weight for a given app installation.
    Establishes an exponential ramp-up period for installations after being updated.
    """
    age = datetime.now(timezone.utc) - installation.created_at
    if age.days >= 10:
        return MAX_GITHUB_APP_SELECTION_WEIGHT
    seconds_in_hour = 3600
    age_hours = (age.seconds // seconds_in_hour) + age.days * 24
    # Prevent clock differences from making the weight negative
    return max(1, age_hours + 2**age.days)


def _can_use_this_app(
    app: GithubAppInstallation, installation_name: str, repository: Optional[Repository]
) -> bool:
    return (
        app.name == installation_name
        # We ignore apps that are not configured because those can't be used
        and app.is_configured()
        and (
            # If there is a repo we want only the apps that cover said repo
            (repository and app.is_repo_covered_by_integration(repository))
            # If there is no repo we still need some true value
            or (not repository)
        )
    )


def _get_apps_from_weighted_selection(
    owner: Owner, installation_name: str, repository: Optional[Repository]
) -> List[GithubAppInstallation]:
    """This function returns an ordered list of GithubAppInstallations that can be used to communicate with GitHub
    in behalf of the owner. The list is ordered in such a way that the 1st element is the app to be used in Torngit,
    and the subsequent apps are selected as fallbacks.

    IF the repository is provided, the selected apps also cover the repo.
    IF installation_name is not the default one, than the default codecov installation
      is also selected as a possible fallback app.

    Apps are selected randomly but assigned weights based on how recently they were created.
    This means that older apps are selected more frequently as the main app than newer ones.
    (up to 10 days, when the probability of being chosen is the same)
    The random selection is done so we can distribute request load more evenly among apps.
    """
    # Map GithubAppInstallation.id --> GithubAppInstallation
    ghapp_installations_filter: Dict[int, GithubAppInstallation] = {
        obj.id: obj
        for obj in filter(
            lambda obj: _can_use_this_app(obj, installation_name, repository),
            owner.github_app_installations or [],
        )
    }
    # We assign weights to the apps based on how long ago they were created.
    # The idea is that there's a greater chance that a change misconfigured the app,
    # So apps recently created are selected less frequently than older apps
    keys = list(ghapp_installations_filter.keys())
    weights = [
        min(
            MAX_GITHUB_APP_SELECTION_WEIGHT,
            _get_installation_weight(ghapp_installations_filter[key]),
        )
        for key in keys
    ]
    # We pick apps one by one until all apps have been selected
    # Obviously apps with a higher weight have a higher change of being selected as the main app (1st selection)
    # But it's important that others are also selected so we can use them as fallbacks
    apps_to_consider = []
    apps_to_select = len(keys)
    selections = 0
    while selections < apps_to_select:
        selected_app_id = random.choices(keys, weights, k=1)[0]
        apps_to_consider.append(ghapp_installations_filter[selected_app_id])
        # random.choices chooses with replacement
        # which we are trying to avoid here. So we remove the key selected and its weight from the population.
        key_idx = keys.index(selected_app_id)
        keys.pop(key_idx)
        weights.pop(key_idx)
        selections += 1
    if installation_name != GITHUB_APP_INSTALLATION_DEFAULT_NAME:
        # Add the default app as the last fallback if the owner is using a different app for the task
        default_apps = filter(
            lambda obj: _can_use_this_app(
                obj, GITHUB_APP_INSTALLATION_DEFAULT_NAME, repository
            ),
            owner.github_app_installations,
        )
        if default_apps:
            apps_to_consider.extend(default_apps)
    return apps_to_consider


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
    ignore_installation: bool = False,
) -> Optional[Dict]:
    log.info(
        "Getting owner installation id",
        extra=dict(
            deprecated_using_integration=deprecated_using_integration,
            installation_name=installation_name,
            ignore_installation=ignore_installation,
            ownerid=owner.ownerid,
            repoid=getattr(repository, "repoid", None),
        ),
    )

    if not ignore_installation or deprecated_using_integration:
        redis_connection = get_redis_connection()
        apps_to_consider = _get_apps_from_weighted_selection(
            owner, installation_name, repository
        )

        apps_matching_criteria_count = len(apps_to_consider)
        apps_to_consider = list(
            filter(
                lambda obj: not is_installation_rate_limited(
                    redis_connection, obj.installation_id, app_id=obj.app_id
                ),
                apps_to_consider,
            )
        )

        if apps_to_consider:
            main_name = apps_to_consider[0].name
            info_to_get_tokens = list(
                map(
                    lambda obj: GithubInstallationInfo(
                        installation_id=obj.installation_id,
                        app_id=obj.app_id,
                        pem_path=obj.pem_path,
                    ),
                    apps_to_consider,
                )
            )
            main_selected_info = info_to_get_tokens.pop(0)
            log.info(
                "Selected installation to communicate with github",
                extra=dict(
                    installation_id=main_selected_info["installation_id"],
                    installation_name=main_name,
                    fallback_installations=[
                        obj["installation_id"] for obj in info_to_get_tokens
                    ],
                ),
            )
            return {**main_selected_info, "fallback_installations": info_to_get_tokens}
        elif apps_matching_criteria_count > 0:
            raise NoConfiguredAppsAvailable(
                apps_count=apps_matching_criteria_count, all_rate_limited=True
            )
    # DEPRECATED FLOW - begin
    if owner.integration_id and deprecated_using_integration:
        log.info("Selected owner integration to communicate with github")
        return {"installation_id": owner.integration_id}
    # DEPRECATED FLOW - end
    return None


def get_repo_appropriate_bot_token(
    repo: Repository,
    installation_info: Optional[Dict] = None,
) -> Tuple[Dict, Optional[Owner]]:
    log.info(
        "Get repo appropriate bot token",
        extra=dict(
            installation_info=installation_info,
            repoid=repo.repoid,
        ),
    )

    if is_enterprise() and get_config(repo.service, "bot"):
        return get_public_bot_token(repo)

    if installation_info:
        github_token = get_github_integration_token(
            repo.owner.service,
            installation_info["installation_id"],
            app_id=installation_info.get("app_id", None),
            pem_path=installation_info.get("pem_path", None),
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

    log.error(
        "No tokenless bot dict in get_public_bot_token",
        extra=dict(repoid=repo.repoid),
    )
    raise RepositoryWithoutValidBotError()


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
    owner, installation_dict: Optional[Dict] = None
) -> Dict:
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
