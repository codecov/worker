import datetime as dt
import json

import pyarrow as pa
import pytest
import time_machine
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.django_apps.reports.tests.factories import (
    DailyTestRollupFactory,
    RepositoryFlagFactory,
    TestFactory,
    TestFlagBridgeFactory,
)

from services.redis import get_redis_connection
from tasks.cache_test_rollups import CacheTestRollupsTask


class TestCacheTestRollupsTask:
    @pytest.fixture(autouse=True)
    def setup(self, transactional_db):
        with time_machine.travel(dt.datetime.now(dt.UTC), tick=False):
            self.repo = RepositoryFactory()
            self.flag = RepositoryFlagFactory(
                repository=self.repo,
                flag_name="test-rollups",
            )
            self.flag2 = RepositoryFlagFactory(
                repository=self.repo,
                flag_name="test-rollups2",
            )
            self.test = TestFactory(repository=self.repo, testsuite="testsuite1")
            self.test2 = TestFactory(repository=self.repo, testsuite="testsuite2")

            _ = TestFlagBridgeFactory(
                test=self.test,
                flag=self.flag,
            )
            _ = TestFlagBridgeFactory(
                test=self.test2,
                flag=self.flag2,
            )

            _ = DailyTestRollupFactory(
                test=self.test,
                commits_where_fail=["123", "456"],
                repoid=self.repo.repoid,
                branch="main",
                pass_count=1,
                date=dt.date.today(),
                latest_run=dt.datetime.now(dt.UTC),
            )
            _ = DailyTestRollupFactory(
                test=self.test2,
                repoid=self.repo.repoid,
                branch="main",
                pass_count=1,
                fail_count=1,
                date=dt.date.today() - dt.timedelta(days=6),
                commits_where_fail=["123"],
                latest_run=dt.datetime.now(dt.UTC),
            )
            _ = DailyTestRollupFactory(
                test=self.test2,
                repoid=self.repo.repoid,
                branch="main",
                pass_count=0,
                fail_count=10,
                date=dt.date.today() - dt.timedelta(days=29),
                commits_where_fail=["123", "789"],
                latest_run=dt.datetime.now(dt.UTC) - dt.timedelta(days=29),
            )

    def test_cache_test_rollups(self, transactional_db):
        with time_machine.travel(dt.datetime.now(dt.UTC), tick=False):
            task = CacheTestRollupsTask()
            result = task.run_impl(
                _db_session=None, repoid=self.repo.repoid, branch="main"
            )
            assert result == {"success": True}

            redis = get_redis_connection()
            buf = redis.get("ta:1:main:1")

            with pa.ipc.open_file(buf) as reader:
                table = reader.read_all()

            assert json.loads(table.to_pandas().to_json(orient="records")) == [
                {
                    "name": "test_0",
                    "test_id": "test_0",
                    "testsuite": "testsuite1",
                    "flags": ["test-rollups"],
                    "failure_rate": 0.0,
                    "flake_rate": 0.0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()) * 1000,
                    "avg_duration": 0.0,
                    "total_fail_count": 0,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "commits_where_fail": 2,
                    "last_duration": 0.0,
                }
            ]

            buf = redis.get("ta:1:main:7")

            with pa.ipc.open_file(buf) as reader:
                table = reader.read_all()

            assert json.loads(table.to_pandas().to_json(orient="records")) == [
                {
                    "name": "test_0",
                    "test_id": "test_0",
                    "testsuite": "testsuite1",
                    "flags": ["test-rollups"],
                    "failure_rate": 0.0,
                    "flake_rate": 0.0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()) * 1000,
                    "avg_duration": 0.0,
                    "total_fail_count": 0,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "commits_where_fail": 2,
                    "last_duration": 0.0,
                },
                {
                    "avg_duration": 0.0,
                    "commits_where_fail": 1,
                    "failure_rate": 0.5,
                    "flags": [
                        "test-rollups2",
                    ],
                    "flake_rate": 0.0,
                    "last_duration": 0.0,
                    "name": "test_1",
                    "test_id": "test_1",
                    "testsuite": "testsuite2",
                    "total_fail_count": 1,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()) * 1000,
                },
            ]

            buf = redis.get("ta:1:main:30")

            with pa.ipc.open_file(buf) as reader:
                table = reader.read_all()

            assert json.loads(table.to_pandas().to_json(orient="records")) == [
                {
                    "name": "test_0",
                    "test_id": "test_0",
                    "testsuite": "testsuite1",
                    "flags": ["test-rollups"],
                    "failure_rate": 0.0,
                    "flake_rate": 0.0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()) * 1000,
                    "avg_duration": 0.0,
                    "total_fail_count": 0,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "commits_where_fail": 2,
                    "last_duration": 0.0,
                },
                {
                    "avg_duration": 0.0,
                    "commits_where_fail": 2,
                    "failure_rate": 0.9166666667,
                    "flags": [
                        "test-rollups2",
                    ],
                    "flake_rate": 0.0,
                    "last_duration": 0.0,
                    "name": "test_1",
                    "test_id": "test_1",
                    "testsuite": "testsuite2",
                    "total_fail_count": 11,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()) * 1000,
                },
                {
                    "avg_duration": 0.0,
                    "commits_where_fail": 2,
                    "failure_rate": 0.9166666667,
                    "flags": [
                        "test-rollups2",
                    ],
                    "flake_rate": 0.0,
                    "last_duration": 0.0,
                    "name": "test_1",
                    "test_id": "test_1",
                    "testsuite": "testsuite2",
                    "total_fail_count": 11,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()) * 1000,
                },
            ]
