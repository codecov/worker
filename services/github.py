import logging
from typing import Optional

from redis import RedisError
from shared.github import InvalidInstallationError
from shared.github import get_github_integration_token as _get_github_integration_token

from database.models.core import Commit
from helpers.cache import cache
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


COMMIT_GHAPP_KEY_NAME = lambda commit_id: f"app_to_use_for_commit_{commit_id}"


def set_github_app_for_commit(
    installation_id: str | int | None, commit: Commit
) -> bool:
    if installation_id is None:
        return False
    redis = get_redis_connection()
    try:
        redis.set(
            COMMIT_GHAPP_KEY_NAME(commit.id), str(installation_id), ex=(60 * 60 * 2)
        )  # 2h
        return True
    except RedisError:
        log.exception(
            "Failed to set app for commit", extra=dict(commit=commit.commitid)
        )
        return False


def get_github_app_for_commit(commit: Commit) -> str | None:
    redis = get_redis_connection()
    try:
        return redis.get(COMMIT_GHAPP_KEY_NAME(commit.id))
    except RedisError:
        log.exception(
            "Failed to get app for commit", extra=dict(commit=commit.commitid)
        )
        return None
