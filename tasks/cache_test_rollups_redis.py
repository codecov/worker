import datetime as dt

from shared.celery_config import cache_test_rollups_redis_task_name
from shared.storage.exceptions import FileNotInStorageError

from services.redis import get_redis_connection
from services.storage import get_storage_client
from tasks.base import BaseCodecovTask


class CacheTestRollupsRedisTask(
    BaseCodecovTask, name=cache_test_rollups_redis_task_name
):
    def run_impl(self, *, repoid: int, branch: str, **kwargs) -> dict[str, bool]:
        storage_service = get_storage_client()

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
                file: bytes = storage_service.read_file("codecov", storage_key)
            except FileNotInStorageError:
                pass

            redis_conn = get_redis_connection()
            redis_key = (
                f"ta_roll:{repoid}:{branch}:{interval_start}"
                if interval_end is None
                else f"ta_roll:{repoid}:{branch}:{interval_start}_{interval_end}"
            )

            redis_conn.set(redis_key, file, ex=dt.timedelta(hours=1).seconds)

        return {"success": True}
