import logging

from redis import Redis
from shared.config import get_config

log = logging.getLogger(__name__)


def get_redis_url() -> str:
    url = get_config("services", "redis_url")
    if url is not None:
        return url
    hostname = "redis"
    port = 6379
    return f"redis://{hostname}:{port}"


def get_redis_connection() -> Redis:
    url = get_redis_url()
    return _get_redis_instance_from_url(url)


def _get_redis_instance_from_url(url) -> Redis:
    return Redis.from_url(url)
