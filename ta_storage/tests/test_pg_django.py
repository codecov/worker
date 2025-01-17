from datetime import datetime, timedelta

import polars as pl
import pytest
from shared.django_apps.reports.models import DailyTestRollup, Flake
from shared.django_apps.reports.tests.factories import (
    DailyTestRollupFactory,
    TestFactory,
    TestInstanceFactory,
    UploadFactory,
)

from services.processing.flake_processing import FLAKE_EXPIRY_COUNT
from ta_storage.pg import PGDriver


def read_table(mock_storage, bucket: str, storage_path: str):
    decompressed_table: bytes = mock_storage.read_file(bucket, storage_path)
    return pl.read_ipc(decompressed_table)


@pytest.mark.django_db(transaction=True)
def test_pg_driver_cache_analytics(mock_storage):
    # Create test data
    upload = UploadFactory()
    upload.save()

    test = TestFactory(
        repository=upload.report.commit.repository,
        name="test_name",
        testsuite="test_suite",
        computed_name="test_computed_name",
    )
    test.save()

    test_instance = TestInstanceFactory(
        test=test,
        upload=upload,
        outcome="pass",
        duration_seconds=1.5,
        commitid=upload.report.commit.commitid,
        branch=upload.report.commit.branch,
        repoid=upload.report.commit.repository.repoid,
    )
    test_instance.save()

    # Create daily rollup data for different intervals
    today = datetime.now().date()

    # Today's data
    rollup_today = DailyTestRollupFactory(
        test=test,
        repoid=test.repository.repoid,
        branch=upload.report.commit.branch,
        date=today,
        pass_count=10,
        fail_count=2,
        skip_count=1,
        flaky_fail_count=1,
        avg_duration_seconds=1.5,
        last_duration_seconds=1.2,
        latest_run=datetime.now(),
        commits_where_fail=[upload.report.commit.commitid],
    )
    rollup_today.save()

    # Yesterday's data
    rollup_yesterday = DailyTestRollupFactory(
        test=test,
        repoid=test.repository.repoid,
        branch=upload.report.commit.branch,
        date=today - timedelta(days=1),
        pass_count=5,
        fail_count=3,
        skip_count=0,
        flaky_fail_count=2,
        avg_duration_seconds=1.8,
        last_duration_seconds=1.4,
        latest_run=datetime.now() - timedelta(days=1),
        commits_where_fail=[upload.report.commit.commitid],
    )
    rollup_yesterday.save()

    # Data from 7 days ago
    rollup_week = DailyTestRollupFactory(
        test=test,
        repoid=test.repository.repoid,
        branch=upload.report.commit.branch,
        date=today - timedelta(days=7),
        pass_count=8,
        fail_count=4,
        skip_count=2,
        flaky_fail_count=3,
        avg_duration_seconds=1.6,
        last_duration_seconds=1.3,
        latest_run=datetime.now() - timedelta(days=7),
        commits_where_fail=[upload.report.commit.commitid],
    )
    rollup_week.save()

    # Data from 30 days ago
    rollup_month = DailyTestRollupFactory(
        test=test,
        repoid=test.repository.repoid,
        branch=upload.report.commit.branch,
        date=today - timedelta(days=30),
        pass_count=15,
        fail_count=5,
        skip_count=3,
        flaky_fail_count=4,
        avg_duration_seconds=1.7,
        last_duration_seconds=1.5,
        latest_run=datetime.now() - timedelta(days=30),
        commits_where_fail=[upload.report.commit.commitid],
    )
    rollup_month.save()

    buckets = ["bucket1", "bucket2"]
    branch = upload.report.commit.branch

    pg = PGDriver(upload.report.commit.repository.repoid)
    pg.cache_analytics(buckets, branch)

    rollups = DailyTestRollup.objects.filter(
        repoid=test.repository.repoid,
        branch=upload.report.commit.branch,
    )

    print(rollups)

    expected_intervals = [
        (1, None),  # Today
        (2, 1),  # Yesterday
        (7, None),  # Last week
        (14, 7),  # Week before last
        (30, None),  # Last month
        (60, 30),  # Month before last
    ]

    # Verify data for each interval in each bucket
    for bucket in buckets:
        for interval_start, interval_end in expected_intervals:
            storage_key = (
                f"test_results/rollups/{upload.report.commit.repository.repoid}/{branch}/{interval_start}"
                if interval_end is None
                else f"test_results/rollups/{upload.report.commit.repository.repoid}/{branch}/{interval_start}_{interval_end}"
            )
            table = read_table(mock_storage, bucket, storage_key)
            table_dict = table.to_dict(as_series=False)

            print(table_dict)
            # Verify data based on intervals
            if (interval_start, interval_end) == (1, None):
                # Today's data
                assert table_dict["total_pass_count"] == [15]
                assert table_dict["total_fail_count"] == [5]
            elif (interval_start, interval_end) == (2, 1):
                # Yesterday's data
                assert table_dict["total_pass_count"] == []
                assert table_dict["total_fail_count"] == []
            elif (interval_start, interval_end) == (7, None):
                # Last week's data (includes today)
                assert table_dict["total_pass_count"] == [23]  # 10 + 5 + 8
                assert table_dict["total_fail_count"] == [9]  # 2 + 3 + 4
            elif (interval_start, interval_end) == (30, None):
                # Last month's data (includes all)
                assert table_dict["total_pass_count"] == [38]  # 10 + 5 + 8 + 15
                assert table_dict["total_fail_count"] == [14]  # 2 + 3 + 4 + 5
            elif (interval_start, interval_end) == (14, 7):
                # Week before last (should be empty since we have no data in this range)
                assert table_dict["total_pass_count"] == []
                assert table_dict["total_fail_count"] == []
            elif (interval_start, interval_end) == (60, 30):
                # Month before last (should be empty)
                assert table_dict["total_pass_count"] == []
                assert table_dict["total_fail_count"] == []


@pytest.mark.django_db(transaction=True)
def test_pg_driver_write_flakes(mock_storage):
    # Create test data
    upload1 = UploadFactory()
    upload1.save()

    test1 = TestFactory(
        repository=upload1.report.commit.repository,
        name="test_name1",
        testsuite="test_suite",
        computed_name="test_computed_name1",
    )
    test1.save()

    test2 = TestFactory(
        repository=upload1.report.commit.repository,
        name="test_name2",
        testsuite="test_suite",
        computed_name="test_computed_name2",
    )
    test2.save()

    # Create a pre-existing flake for test1
    flake1 = Flake.objects.create(
        repository=test1.repository,
        test=test1,
        fail_count=1,
        count=1,
        recent_passes_count=0,
        start_date=datetime.now(),
    )
    flake1.save()

    # Create test instances that will update the existing flake
    test_instance1 = TestInstanceFactory(
        test=test1,
        upload=upload1,
        outcome="pass",  # This should increment recent_passes_count
        duration_seconds=1.5,
        commitid=upload1.report.commit.commitid,
        branch=upload1.report.commit.branch,
        repoid=upload1.report.commit.repository.repoid,
    )
    test_instance1.save()

    # Create test instances that will create a new flake
    test_instance2 = TestInstanceFactory(
        test=test2,
        upload=upload1,
        outcome="failure",  # This should create a new flake
        duration_seconds=1.8,
        failure_message="Test failed",
        commitid=upload1.report.commit.commitid,
        branch=upload1.report.commit.branch,
        repoid=upload1.report.commit.repository.repoid,
    )
    test_instance2.save()

    # Create another upload with more test instances
    upload2 = UploadFactory()
    upload2.save()

    # Create test instances that will expire the flake
    for _ in range(FLAKE_EXPIRY_COUNT - 1):  # -1 because we already have one pass
        test_instance = TestInstanceFactory(
            test=test1,
            upload=upload2,
            outcome="pass",  # These passes should eventually expire the flake
            duration_seconds=1.5,
            commitid=upload2.report.commit.commitid,
            branch=upload2.report.commit.branch,
            repoid=upload2.report.commit.repository.repoid,
        )
        test_instance.save()

    pg = PGDriver(upload1.report.commit.repository.repoid)
    pg.write_flakes([upload1, upload2])

    # Verify the flakes
    flakes = Flake.objects.filter(repository=test1.repository).order_by("test")

    # Verify the first flake (should be expired)
    assert flakes[0].test == test1
    assert flakes[0].count == FLAKE_EXPIRY_COUNT + 1  # Original + all passes
    assert flakes[0].fail_count == 1  # Unchanged
    assert flakes[0].recent_passes_count == FLAKE_EXPIRY_COUNT
    assert flakes[0].end_date is not None  # Should be expired

    # Verify the second flake (newly created)
    assert flakes[1].test == test2
    assert flakes[1].count == 1
    assert flakes[1].fail_count == 1
    assert flakes[1].recent_passes_count == 0
    assert flakes[1].end_date is None  # Should not be expired
