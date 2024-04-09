import logging
import zlib
from typing import Optional

from redis import Redis
from shared.config import get_config

log = logging.getLogger(__name__)

# The purpose of this key is to synchronize allocation of session IDs
# when processing reports in parallel. If multiple uploads are processed
# at a time, they all need to know what session id to use when generating
# their chunks.txt. This is because in UploadFinisher, they will all be
# combined together and need to all have unique session IDs.

# This key is a counter that will hold an integer, representing the smallest
# session ID that is available to be claimed. It can be claimed by incrementing
# the key.
PARALLEL_UPLOAD_PROCESSING_SESSION_COUNTER_REDIS_KEY = (
    "parallel_session_counter:{repoid}:{commitid}"
)

PARALLEL_UPLOAD_PROCESSING_SESSION_COUNTER_TTL = (
    10800  # 3 hours, chosen somewhat arbitrarily
)


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


def download_archive_from_redis(
    redis_connection: Redis, redis_key: str
) -> Optional[str]:
    raw_uploaded_report = redis_connection.get(redis_key)
    gzipped = redis_key.endswith("/gzip")
    if gzipped:
        raw_uploaded_report = zlib.decompress(raw_uploaded_report, zlib.MAX_WBITS | 16)
    if raw_uploaded_report is not None:
        return raw_uploaded_report.decode()
    return None


def get_parallel_upload_processing_session_counter_redis_key(repoid, commitid):
    return PARALLEL_UPLOAD_PROCESSING_SESSION_COUNTER_REDIS_KEY.format(
        repoid=repoid, commitid=commitid
    )
