import datetime as dt

import polars as pl
import pytest
from shared.django_apps.timeseries.models import (
    Testrun,
    TestrunBranchSummary,
    TestrunSummary,
)
from time_machine import travel

from services.test_analytics.utils import calc_test_id
from tasks.cache_test_rollups import CacheTestRollupsTask


def read_table(mock_storage, storage_path: str):
    decompressed_table: bytes = mock_storage.read_file("codecov", storage_path)
    return pl.read_ipc(decompressed_table)


@pytest.mark.django_db(databases=["timeseries"], transaction=True)
@travel("2025-01-01T00:00:00Z", tick=False)
def test_cache_test_rollups(mock_storage, snapshot):
    TestrunSummary.objects.create(
        timestamp_bin=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        repo_id=1,
        name="name",
        classname="classname",
        testsuite="testsuite",
        computed_name="computed_name",
        failing_commits=1,
        avg_duration_seconds=100,
        last_duration_seconds=100,
        pass_count=0,
        fail_count=1,
        skip_count=0,
        flaky_fail_count=0,
        updated_at=dt.datetime.now(dt.timezone.utc),
        flags=["test-rollups"],
    )

    TestrunSummary.objects.create(
        timestamp_bin=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        repo_id=1,
        name="name2",
        classname="classname2",
        testsuite="testsuite2",
        computed_name="computed_name2",
        failing_commits=2,
        avg_duration_seconds=200,
        last_duration_seconds=200,
        pass_count=0,
        fail_count=2,
        skip_count=0,
        flaky_fail_count=0,
        updated_at=dt.datetime.now(dt.timezone.utc),
        flags=["test-rollups2"],
    )

    TestrunSummary.objects.create(
        timestamp_bin=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=61),
        repo_id=1,
        name="name3",
        classname="classname3",
        testsuite="testsuite3",
        computed_name="computed_name3",
        failing_commits=2,
        avg_duration_seconds=200,
        last_duration_seconds=200,
        pass_count=0,
        fail_count=2,
        skip_count=0,
        flaky_fail_count=0,
        updated_at=dt.datetime.now(dt.timezone.utc),
        flags=["test-rollups3"],
    )

    CacheTestRollupsTask().run_impl(
        _db_session=None,
        repoid=1,
        branch=None,
        impl_type="new",
    )

    table = read_table(mock_storage, "test_analytics/repo_rollups/1.arrow")
    table_dict = table.to_dict(as_series=False)
    table_dict["timestamp_bin"] = [ts.isoformat() for ts in table_dict["timestamp_bin"]]
    table_dict["updated_at"] = [ts.isoformat() for ts in table_dict["updated_at"]]
    assert snapshot("json") == table_dict


@pytest.mark.django_db(databases=["timeseries"], transaction=True)
@travel("2025-01-01T00:00:00Z", tick=False)
def test_cache_test_rollups_use_timeseries_main(mock_storage, snapshot):
    TestrunBranchSummary.objects.create(
        timestamp_bin=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        repo_id=1,
        branch="main",
        name="name",
        classname="classname",
        testsuite="testsuite",
        computed_name="computed_name",
        failing_commits=1,
        avg_duration_seconds=100,
        last_duration_seconds=100,
        pass_count=0,
        fail_count=1,
        skip_count=0,
        flaky_fail_count=0,
        updated_at=dt.datetime.now(dt.timezone.utc),
        flags=["test-rollups"],
    )

    TestrunBranchSummary.objects.create(
        timestamp_bin=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        repo_id=1,
        branch="main",
        name="name2",
        classname="classname2",
        testsuite="testsuite2",
        computed_name="computed_name2",
        failing_commits=2,
        avg_duration_seconds=200,
        last_duration_seconds=200,
        pass_count=0,
        fail_count=2,
        skip_count=0,
        flaky_fail_count=0,
        updated_at=dt.datetime.now(dt.timezone.utc),
        flags=["test-rollups2"],
    )

    TestrunBranchSummary.objects.create(
        timestamp_bin=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=61),
        repo_id=1,
        branch="main",
        name="name3",
        classname="classname3",
        testsuite="testsuite3",
        computed_name="computed_name3",
        failing_commits=2,
        avg_duration_seconds=200,
        last_duration_seconds=200,
        pass_count=0,
        fail_count=2,
        skip_count=0,
        flaky_fail_count=0,
        updated_at=dt.datetime.now(dt.timezone.utc),
        flags=["test-rollups3"],
    )

    TestrunBranchSummary.objects.create(
        timestamp_bin=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        repo_id=1,
        branch="feature",
        name="name4",
        classname="classname4",
        testsuite="testsuite4",
        computed_name="computed_name4",
        failing_commits=2,
        avg_duration_seconds=200,
        last_duration_seconds=200,
        pass_count=0,
        fail_count=2,
        skip_count=0,
        flaky_fail_count=0,
        updated_at=dt.datetime.now(dt.timezone.utc),
        flags=["test-rollups3"],
    )

    CacheTestRollupsTask().run_impl(
        _db_session=None,
        repoid=1,
        branch="main",
        impl_type="new",
    )


@pytest.mark.django_db(databases=["timeseries"], transaction=True)
@travel("2025-01-01T00:00:00Z", tick=False)
def test_cache_test_rollups_use_timeseries_branch(mock_storage, snapshot):
    Testrun.objects.create(
        timestamp=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        test_id=calc_test_id("name", "classname", "testsuite"),
        name="name",
        classname="classname",
        testsuite="testsuite",
        computed_name="computed_name",
        outcome="pass",
        duration_seconds=100,
        failure_message="failure_message",
        framework="framework",
        filename="filename",
        repo_id=1,
        commit_sha="commit_sha",
        branch="feature",
        flags=["test-rollups"],
        upload_id=1,
    )

    Testrun.objects.create(
        timestamp=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=61),
        test_id=calc_test_id("name2", "classname2", "testsuite2"),
        name="name2",
        classname="classname2",
        testsuite="testsuite2",
        computed_name="computed_name2",
        outcome="pass",
        duration_seconds=100,
        failure_message="failure_message",
        framework="framework",
        filename="filename",
        repo_id=1,
        commit_sha="commit_sha",
        branch="feature",
        flags=["test-rollups"],
        upload_id=1,
    )

    Testrun.objects.create(
        timestamp=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=61),
        test_id=calc_test_id("name3", "classname3", "testsuite3"),
        name="name3",
        classname="classname3",
        testsuite="testsuite3",
        computed_name="computed_name3",
        outcome="pass",
        duration_seconds=100,
        failure_message="failure_message",
        framework="framework",
        filename="filename",
        repo_id=1,
        commit_sha="commit_sha",
        branch="main",
        flags=["test-rollups"],
        upload_id=1,
    )

    CacheTestRollupsTask().run_impl(
        _db_session=None,
        repoid=1,
        branch="feature",
        impl_type="new",
    )

    table = read_table(mock_storage, "test_analytics/branch_rollups/1/feature.arrow")
    table_dict = table.to_dict(as_series=False)
    table_dict["timestamp_bin"] = [ts.isoformat() for ts in table_dict["timestamp_bin"]]
    table_dict["updated_at"] = [ts.isoformat() for ts in table_dict["updated_at"]]
    assert snapshot("json") == table_dict
