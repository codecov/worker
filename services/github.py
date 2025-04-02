import logging
from typing import Optional

from redis import RedisError
from shared.github import InvalidInstallationError
from shared.github import get_github_integration_token as _get_github_integration_token
from shared.helpers.cache import cache

from database.models.core import Commit
from helpers.exceptions import RepositoryWithoutValidBotError
from services.redis import get_redis_connection

log = logging.getLogger(__name__)


@cache.cache_function(ttl=480)
def get_github_integration_token(
    service: str,
    installation_id: int = None,
    app_id: Optional[str] = None,
    pem_path: Optional[str] = None,
):
    try:
        return _get_github_integration_token(
            service, integration_id=installation_id, app_id=app_id, pem_path=pem_path
        )
    except InvalidInstallationError:
        log.warning("Failed to get installation token")
        raise RepositoryWithoutValidBotError()


def COMMIT_GHAPP_KEY_NAME(commit_id):
    return f"app_to_use_for_commit_{commit_id}"


GHAPP_KEY_EXPIRY_SECONDS = 60 * 60 * 2  # 2h


def set_github_app_for_commit(
    installation_id: str | int | None, commit: Commit
) -> bool:
    """Sets a GithubAppInstallation.id in Redis as the installation to use for a commit.
    Keys live in redis for GHAPP_KEY_EXPIRY_SECONDS before being expired.

    Args:
        installation_id (str | int | None) - the ID to save.
          None -- there was actually no installation ID. Do nothing.
          int -- value comes from the Database
          str -- value comes from Redis (i.e. the installation was already cached)
        commit (Commit) - the commit to attach installation_id to
    """
    if installation_id is None:
        return False
    redis = get_redis_connection()
    try:
        redis.set(
            COMMIT_GHAPP_KEY_NAME(commit.id),
            str(installation_id),
            ex=GHAPP_KEY_EXPIRY_SECONDS,
        )
        return True
    except RedisError:
        log.exception(
            "Failed to set app for commit", extra=dict(commit=commit.commitid)
        )
        return False


def get_github_app_for_commit(commit: Commit) -> str | None:
    if commit.repository.service not in ["github", "github_enterprise"]:
        # Because this feature is GitHub-exclusive we can skip checking for other providers
        return None
    redis = get_redis_connection()
    try:
        value = redis.get(COMMIT_GHAPP_KEY_NAME(commit.id))
        return value if value is None else value.decode()
    except RedisError:
        log.exception(
            "Failed to get app for commit", extra=dict(commit=commit.commitid)
        )
        return None
