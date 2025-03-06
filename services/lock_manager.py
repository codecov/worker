import logging
import random
from contextlib import contextmanager
from enum import Enum
from typing import Optional

from redis import Redis
from redis.exceptions import LockError

from database.enums import ReportType
from services.redis import get_redis_connection

log = logging.getLogger(__name__)


class LockType(Enum):
    BUNDLE_ANALYSIS_PROCESSING = "bundle_analysis_processing"
    BUNDLE_ANALYSIS_NOTIFY = "bundle_analysis_notify"
    NOTIFICATION = "notify"
    # TODO: port existing task locking to use `LockManager`


class LockRetry(Exception):
    def __init__(self, countdown: int):
        self.countdown = countdown


class LockManager:
    def __init__(
        self,
        repoid: int,
        commitid: str,
        report_type=ReportType.COVERAGE,
        lock_timeout=300,  # 5 min
        redis_connection: Optional[Redis] = None,
    ):
        self.repoid = repoid
        self.commitid = commitid
        self.report_type = report_type
        self.lock_timeout = lock_timeout
        self.redis_connection = redis_connection or get_redis_connection()

    def lock_name(self, lock_type: LockType):
        if self.report_type == ReportType.COVERAGE:
            # for backward compat this does not include the report type
            return f"{lock_type.value}_lock_{self.repoid}_{self.commitid}"
        else:
            return f"{lock_type.value}_lock_{self.repoid}_{self.commitid}_{self.report_type.value}"

    def is_locked(self, lock_type: LockType) -> bool:
        lock_name = self.lock_name(lock_type)
        if self.redis_connection.get(lock_name):
            return True
        return False

    @contextmanager
    def locked(self, lock_type: LockType, retry_num=0):
        lock_name = self.lock_name(lock_type)
        try:
            log.info(
                "Acquiring lock",
                extra=dict(
                    repoid=self.repoid,
                    commitid=self.commitid,
                    lock_name=lock_name,
                ),
            )
            with self.redis_connection.lock(
                lock_name, timeout=self.lock_timeout, blocking_timeout=5
            ):
                log.info(
                    "Acquired lock",
                    extra=dict(
                        repoid=self.repoid,
                        commitid=self.commitid,
                        lock_name=lock_name,
                    ),
                )
                yield
                log.info(
                    "Releasing lock",
                    extra=dict(
                        repoid=self.repoid,
                        commitid=self.commitid,
                        lock_name=lock_name,
                    ),
                )
        except LockError:
            max_retry = 200 * 3**retry_num
            countdown = min(random.randint(max_retry // 2, max_retry), 60 * 60 * 5)

            log.warning(
                "Unable to acquire lock",
                extra=dict(
                    repoid=self.repoid,
                    commitid=self.commitid,
                    lock_name=lock_name,
                    countdown=countdown,
                    retry_num=retry_num,
                ),
            )
            raise LockRetry(countdown)
