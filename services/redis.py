from helpers.config import get_config
from redis import Redis


def get_redis_connection():
    url = get_config('services', 'redis_url')
    return Redis.from_url(url)
