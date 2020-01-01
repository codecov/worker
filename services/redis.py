import logging
import zlib

from covreports.config import get_config
from redis import Redis

log = logging.getLogger(__name__)


def get_redis_url():
    url = get_config('services', 'redis_url')
    if url is not None:
        return url
    hostname = 'redis'
    port = 6379
    return f'redis://redis:@{hostname}:{port}'


def get_redis_connection() -> Redis:
    url = get_redis_url()
    return _get_redis_instance_from_url(url)


def _get_redis_instance_from_url(url):
    return Redis.from_url(url)


def download_archive_from_redis(redis_connection, redis_key):
    raw_uploaded_report = redis_connection.get(redis_key)
    gzipped = redis_key.endswith('/gzip')
    if gzipped:
        raw_uploaded_report = zlib.decompress(
            raw_uploaded_report, zlib.MAX_WBITS | 16
        )
    if raw_uploaded_report is not None:
        return raw_uploaded_report.decode()
    return None
