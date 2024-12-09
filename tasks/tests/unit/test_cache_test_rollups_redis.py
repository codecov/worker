import polars as pl
import shared.storage
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.storage.exceptions import BucketAlreadyExistsError

from services.redis import get_redis_connection
from tasks.cache_test_rollups_redis import CacheTestRollupsRedisTask


class TestCacheTestRollupsTask:
    def read_table(self, mock_storage, storage_path: str):
        decompressed_table: bytes = mock_storage.read_file("codecov", storage_path)
        return pl.read_ipc(decompressed_table)

    def test_cache_test_rollups(self, mock_storage, transactional_db):
        repo = RepositoryFactory()

        redis = get_redis_connection()
        storage_service = shared.storage.get_appropriate_storage_service(repo.repoid)
        storage_key = f"test_results/rollups/{repo.repoid}/main/1"
        try:
            storage_service.create_root_storage("codecov")
        except BucketAlreadyExistsError:
            pass

        storage_service.write_file("codecov", storage_key, b"hello world")

        task = CacheTestRollupsRedisTask()
        result = task.run_impl(_db_session=None, repoid=repo.repoid, branch="main")
        assert result == {"success": True}

        redis_key = f"ta_roll:{repo.repoid}:main:1"

        assert redis.get(redis_key) == storage_service.read_file("codecov", storage_key)
