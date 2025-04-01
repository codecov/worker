import datetime as dt

import polars as pl
import time_machine
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.django_apps.reports.models import LastCacheRollupDate
from shared.django_apps.reports.tests.factories import (
    DailyTestRollupFactory,
    LastCacheRollupDateFactory,
    RepositoryFlagFactory,
    TestFactory,
    TestFlagBridgeFactory,
)

from tasks.cache_test_rollups import CacheTestRollupsTask


class TestCacheTestRollupsTask:
    def read_table(self, mock_storage, storage_path: str):
        decompressed_table: bytes = mock_storage.read_file("archive", storage_path)
        return pl.read_ipc(decompressed_table)

    def test_cache_test_rollups(self, mock_storage, transactional_db):
        with time_machine.travel(dt.datetime.now(dt.timezone.utc), tick=False):
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
                latest_run=dt.datetime.now(dt.timezone.utc),
            )
            r = DailyTestRollupFactory(
                test=self.test2,
                repoid=self.repo.repoid,
                branch="main",
                pass_count=1,
                fail_count=1,
                date=dt.date.today() - dt.timedelta(days=6),
                commits_where_fail=["123"],
                latest_run=dt.datetime.now(dt.timezone.utc),
            )
            r.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            r.save()
            _ = DailyTestRollupFactory(
                test=self.test2,
                repoid=self.repo.repoid,
                branch="main",
                pass_count=0,
                fail_count=10,
                date=dt.date.today() - dt.timedelta(days=29),
                commits_where_fail=["123", "789"],
                latest_run=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=29),
            )
            _ = DailyTestRollupFactory(
                test=self.test3,
                repoid=self.repo.repoid,
                branch="main",
                pass_count=0,
                fail_count=10,
                date=dt.date.today() - dt.timedelta(days=50),
                commits_where_fail=["123", "789"],
                latest_run=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=50),
            )

            task = CacheTestRollupsTask()
            result = task.run_impl(
                _db_session=None, repo_id=self.repo.repoid, branch="main"
            )
            assert result == {"success": True}

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/1"
            table = self.read_table(mock_storage, storage_key)

            assert table.to_dict(as_series=False) == {
                "avg_duration": [0.0],
                "commits_where_fail": [2],
                "failure_rate": [0.0],
                "flags": [["test-rollups"]],
                "flake_rate": [0.0],
                "last_duration": [0.0],
                "name": [self.test.name],
                "test_id": [self.test.id],
                "testsuite": [self.test.testsuite],
                "total_fail_count": [0],
                "total_flaky_fail_count": [0],
                "total_pass_count": [1],
                "total_skip_count": [0],
                "updated_at": [dt.datetime.now(dt.timezone.utc)],
            }

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/7"
            table = self.read_table(mock_storage, storage_key)

            assert table.to_dict(as_series=False) == {
                "avg_duration": [0.0, 0.0],
                "commits_where_fail": [2, 1],
                "failure_rate": [0.0, 0.5],
                "flags": [["test-rollups"], ["test-rollups2"]],
                "flake_rate": [0.0, 0.0],
                "last_duration": [0.0, 0.0],
                "name": [self.test.name, self.test2.name],
                "test_id": [self.test.id, self.test2.id],
                "testsuite": [self.test.testsuite, self.test2.testsuite],
                "total_fail_count": [0, 1],
                "total_flaky_fail_count": [0, 0],
                "total_pass_count": [1, 1],
                "total_skip_count": [0, 0],
                "updated_at": [
                    dt.datetime.now(dt.timezone.utc),
                    dt.datetime.now(dt.timezone.utc),
                ],
            }

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/30"
            table = self.read_table(mock_storage, storage_key)

            assert table.to_dict(as_series=False) == {
                "avg_duration": [0.0, 0.0],
                "commits_where_fail": [2, 2],
                "failure_rate": [0.0, 0.9166666666666666],
                "flags": [["test-rollups"], ["test-rollups2"]],
                "flake_rate": [0.0, 0.0],
                "last_duration": [0.0, 0.0],
                "name": [self.test.name, self.test2.name],
                "test_id": [self.test.id, self.test2.id],
                "testsuite": [self.test.testsuite, self.test2.testsuite],
                "total_fail_count": [0, 11],
                "total_flaky_fail_count": [0, 0],
                "total_pass_count": [1, 1],
                "total_skip_count": [0, 0],
                "updated_at": [
                    dt.datetime.now(dt.timezone.utc),
                    dt.datetime.now(dt.timezone.utc),
                ],
            }

            storage_key = f"test_results/rollups/{self.repo.repoid}/main/60_30"
            table = self.read_table(mock_storage, storage_key)

            assert table.to_dict(as_series=False) == {
                "name": [self.test3.name],
                "test_id": [self.test3.id],
                "testsuite": [self.test3.testsuite],
                "flags": [None],
                "failure_rate": [1.0],
                "flake_rate": [0.0],
                "updated_at": [
                    dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=50)
                ],
                "avg_duration": [0.0],
                "total_fail_count": [10],
                "total_flaky_fail_count": [0],
                "total_pass_count": [0],
                "total_skip_count": [0],
                "commits_where_fail": [2],
                "last_duration": [0.0],
            }

    def test_cache_test_rollups_no_update_date(self, mock_storage, transactional_db):
        with time_machine.travel(dt.datetime.now(dt.UTC), tick=False):
            self.repo = RepositoryFactory()
            rollup_date = LastCacheRollupDateFactory(
                repository=self.repo,
                last_rollup_date=dt.date.today() - dt.timedelta(days=30),
            )

            task = CacheTestRollupsTask()
            _ = task.run_impl(
                _db_session=None,
                repo_id=rollup_date.repository_id,
                branch=rollup_date.branch,
                update_date=False,
            )

            obj = LastCacheRollupDate.objects.filter(
                repository_id=self.repo.repoid, branch="main"
            ).first()
            assert obj.last_rollup_date == dt.date.today() - dt.timedelta(days=30)

    def test_cache_test_rollups_update_date(self, mock_storage, transactional_db):
        with time_machine.travel(dt.datetime.now(dt.UTC), tick=False):
            self.repo = RepositoryFactory()

            rollup_date = LastCacheRollupDateFactory(
                repository=self.repo,
                last_rollup_date=dt.date.today() - dt.timedelta(days=1),
            )

            task = CacheTestRollupsTask()
            _ = task.run_impl(
                _db_session=None,
                repo_id=rollup_date.repository_id,
                branch="main",
                update_date=True,
            )

            obj = LastCacheRollupDate.objects.filter(
                repository_id=self.repo.repoid, branch="main"
            ).first()
            assert obj.last_rollup_date == dt.date.today()

    def test_cache_test_rollups_update_date_does_not_exist(
        self, mock_storage, transactional_db
    ):
        self.repo = RepositoryFactory()
        with time_machine.travel(dt.datetime.now(dt.UTC), tick=False):
            task = CacheTestRollupsTask()
            _ = task.run_impl(
                _db_session=None,
                repo_id=self.repo.repoid,
                branch="main",
                update_date=True,
            )

            obj = LastCacheRollupDate.objects.filter(
                repository_id=self.repo.repoid, branch="main"
            ).first()
            assert obj.last_rollup_date == dt.date.today()

    def test_cache_test_rollups_both(self, mock_storage, transactional_db, mocker):
        mock_cache_rollups = mocker.patch("tasks.cache_test_rollups.cache_rollups")
        task = CacheTestRollupsTask()
        mocker.patch.object(task, "run_impl_within_lock")
        self.repo = RepositoryFactory()
        with time_machine.travel(dt.datetime.now(dt.UTC), tick=False):
            _ = task.run_impl(
                _db_session=None,
                repo_id=self.repo.repoid,
                branch="main",
                update_date=True,
                impl_type="both",
            )

        mock_cache_rollups.assert_has_calls(
            [
                mocker.call(self.repo.repoid, "main"),
                mocker.call(self.repo.repoid, None),
            ]
        )

        task.run_impl_within_lock.assert_called_once()
