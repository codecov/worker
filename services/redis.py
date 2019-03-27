import os

from helpers.config import get_config
from redis import Redis


def get_redis_connection():
    url = os.getenv("REDIS_URL")
    return Redis.from_url(url)
