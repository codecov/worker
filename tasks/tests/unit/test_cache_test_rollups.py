import datetime as dt
import json

import polars as pl
import pytest
import time_machine
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.django_apps.reports.tests.factories import (
    DailyTestRollupFactory,
    RepositoryFlagFactory,
    TestFactory,
    TestFlagBridgeFactory,
)

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
            self.test3 = TestFactory(repository=self.repo, testsuite="testsuite3")

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
            r = DailyTestRollupFactory(
                test=self.test2,
                repoid=self.repo.repoid,
                branch="main",
                pass_count=1,
                fail_count=1,
                date=dt.date.today() - dt.timedelta(days=6),
                commits_where_fail=["123"],
                latest_run=dt.datetime.now(dt.UTC),
            )
            r.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
            r.save()
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
            _ = DailyTestRollupFactory(
                test=self.test3,
                repoid=self.repo.repoid,
                branch="main",
                pass_count=0,
                fail_count=10,
                date=dt.date.today() - dt.timedelta(days=50),
                commits_where_fail=["123", "789"],
                latest_run=dt.datetime.now(dt.UTC) - dt.timedelta(days=50),
            )

    def read_table(self, mock_storage, storage_path: str):
        decompressed_table: bytes = mock_storage.read_file("codecov", storage_path)
        return pl.read_ipc(decompressed_table)

    def test_cache_test_rollups(self, mock_storage, transactional_db):
        with time_machine.travel(dt.datetime.now(dt.UTC), tick=False):
            task = CacheTestRollupsTask()
            result = task.run_impl(
                _db_session=None, repoid=self.repo.repoid, branch="main"
            )
            assert result == {"success": True}

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/1"
            table = self.read_table(mock_storage, storage_key)

            assert json.loads(table.to_pandas().to_json(orient="records")) == [
                {
                    "name": self.test.name,
                    "test_id": self.test.id,
                    "testsuite": self.test.testsuite,
                    "flags": ["test-rollups"],
                    "failure_rate": 0.0,
                    "flake_rate": 0.0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()),
                    "avg_duration": 0.0,
                    "total_fail_count": 0,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "commits_where_fail": 2,
                    "last_duration": 0.0,
                }
            ]

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/7"
            table = self.read_table(mock_storage, storage_key)

            assert json.loads(table.to_pandas().to_json(orient="records")) == [
                {
                    "name": self.test.name,
                    "test_id": self.test.id,
                    "testsuite": self.test.testsuite,
                    "flags": ["test-rollups"],
                    "failure_rate": 0.0,
                    "flake_rate": 0.0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()),
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
                    "name": self.test2.name,
                    "test_id": self.test2.id,
                    "testsuite": self.test2.testsuite,
                    "total_fail_count": 1,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()),
                },
            ]

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/30"
            table = self.read_table(mock_storage, storage_key)

            assert json.loads(table.to_pandas().to_json(orient="records")) == [
                {
                    "name": self.test.name,
                    "test_id": self.test.id,
                    "testsuite": self.test.testsuite,
                    "flags": ["test-rollups"],
                    "failure_rate": 0.0,
                    "flake_rate": 0.0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()),
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
                    "name": self.test2.name,
                    "test_id": self.test2.id,
                    "testsuite": self.test2.testsuite,
                    "total_fail_count": 11,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 1,
                    "total_skip_count": 0,
                    "updated_at": int(dt.datetime.now(dt.UTC).timestamp()),
                },
            ]

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/60_30"
            table = self.read_table(mock_storage, storage_key)

            assert json.loads(table.to_pandas().to_json(orient="records")) == [
                {
                    "name": self.test3.name,
                    "test_id": self.test3.id,
                    "testsuite": self.test3.testsuite,
                    "flags": None,
                    "failure_rate": 1.0,
                    "flake_rate": 0.0,
                    "updated_at": int(
                        (dt.datetime.now(dt.UTC) - dt.timedelta(days=50)).timestamp()
                    ),
                    "avg_duration": 0.0,
                    "total_fail_count": 10,
                    "total_flaky_fail_count": 0,
                    "total_pass_count": 0,
                    "total_skip_count": 0,
                    "commits_where_fail": 2,
                    "last_duration": 0.0,
                },
            ]
