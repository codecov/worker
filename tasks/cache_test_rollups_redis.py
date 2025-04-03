import datetime as dt

import shared.storage
from redis.exceptions import LockError
from shared.celery_config import cache_test_rollups_redis_task_name
from shared.helpers.redis import get_redis_connection
from shared.storage.exceptions import FileNotInStorageError

from app import celery_app
from django_scaffold import settings
from tasks.base import BaseCodecovTask


class CacheTestRollupsRedisTask(
    BaseCodecovTask, name=cache_test_rollups_redis_task_name
):
    def run_impl(
        self, _db_session, repoid: int, branch: str, **kwargs
    ) -> dict[str, bool]:
        redis_conn = get_redis_connection()
        try:
            with redis_conn.lock(
                f"rollups:{repoid}:{branch}", timeout=300, blocking_timeout=2
            ):
                self.run_impl_within_lock(repoid, branch)
                return {"success": True}
        except LockError:
            return {"in_progress": True}

    def run_impl_within_lock(self, repoid, branch) -> None:
        storage_service = shared.storage.get_appropriate_storage_service(repoid)
        redis_conn = get_redis_connection()

        for interval_start, interval_end in [
            (1, None),
            (7, None),
            (30, None),
            (2, 1),
            (14, 7),
            (60, 30),
        ]:
            storage_key = (
                f"test_results/rollups/{repoid}/{branch}/{interval_start}"
                if interval_end is None
                else f"test_results/rollups/{repoid}/{branch}/{interval_start}_{interval_end}"
            )
            try:
                file: bytes = storage_service.read_file(
                    settings.GCS_BUCKET_NAME, storage_key
                )
            except FileNotInStorageError:
                pass

            redis_key = (
                f"ta_roll:{repoid}:{branch}:{interval_start}"
                if interval_end is None
                else f"ta_roll:{repoid}:{branch}:{interval_start}_{interval_end}"
            )

            redis_conn.set(redis_key, file, ex=dt.timedelta(hours=1).seconds)

        return


RegisteredCacheTestRollupsRedisTask = celery_app.register_task(
    CacheTestRollupsRedisTask()
)
cache_test_rollups_redis_task = celery_app.tasks[
    RegisteredCacheTestRollupsRedisTask.name
]
