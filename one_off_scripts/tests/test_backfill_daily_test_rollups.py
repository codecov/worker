import datetime as dt

import pytest
import time_machine
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.django_apps.reports.models import DailyTestRollup
from shared.django_apps.reports.tests.factories import (
    DailyTestRollupFactory,
    FlakeFactory,
    TestFactory,
    TestInstanceFactory,
)

from one_off_scripts.backfill_daily_test_rollups import backfill_test_rollups


@pytest.fixture
def setup_tests(transactional_db):
    repo_1 = RepositoryFactory(test_analytics_enabled=True)

    test_1 = TestFactory(repository=repo_1)

    _ = FlakeFactory(
        test=test_1,
        repository=repo_1,
        start_date=dt.datetime.fromisoformat("1970-01-02T00:00:00Z"),
        end_date=dt.datetime.fromisoformat("1970-01-04T00:00:00Z"),
    )

    _ = FlakeFactory(
        test=test_1,
        repository=repo_1,
        start_date=dt.datetime.fromisoformat("1970-01-04T12:00:00Z"),
        end_date=None,
    )

    traveller = time_machine.travel("1970-01-01T00:00:00Z", tick=False)
    traveller.start()
    ti = TestInstanceFactory(test=test_1, duration_seconds=10.0)
    traveller.stop()

    traveller = time_machine.travel("1970-01-03T00:00:00Z", tick=False)
    traveller.start()
    ti = TestInstanceFactory(test=test_1, duration_seconds=10.0)
    traveller.stop()

    traveller = time_machine.travel("1970-01-05T00:00:00Z", tick=False)
    traveller.start()
    ti = TestInstanceFactory(
        test=test_1,
        duration_seconds=10000.0,
    )
    traveller.stop()

    _ = DailyTestRollupFactory(
        test=test_1,
        date=dt.date.fromisoformat("1970-01-03"),
        fail_count=10,
        pass_count=5,
        last_duration_seconds=10.0,
        avg_duration_seconds=1.0,
        latest_run=dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
    )

    _ = DailyTestRollupFactory(
        test=test_1,
        date=dt.date.fromisoformat("1970-01-05"),
        fail_count=10,
        pass_count=5,
        last_duration_seconds=10.0,
        avg_duration_seconds=1.0,
        latest_run=dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
    )

    _ = RepositoryFactory(test_analytics_enabled=False)

    return repo_1


@pytest.mark.django_db(transaction=True)
def test_backfill_test_rollups(setup_tests):
    rollups = DailyTestRollup.objects.all()
    assert [
        {
            "date": r.date,
            "pass_count": r.pass_count,
            "skip_count": r.skip_count,
            "fail_count": r.fail_count,
            "flaky_fail_count": r.flaky_fail_count,
            "last_duration_seconds": r.last_duration_seconds,
            "avg_duration_seconds": r.avg_duration_seconds,
            "latest_run": r.latest_run,
            "commits_where_fail": r.commits_where_fail,
        }
        for r in rollups
    ] == [
        {
            "avg_duration_seconds": 1.0,
            "commits_where_fail": [],
            "date": dt.date(1970, 1, 3),
            "fail_count": 10,
            "flaky_fail_count": 0,
            "last_duration_seconds": 10.0,
            "latest_run": dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
            "pass_count": 5,
            "skip_count": 0,
        },
        {
            "avg_duration_seconds": 1.0,
            "commits_where_fail": [],
            "date": dt.date(1970, 1, 5),
            "fail_count": 10,
            "flaky_fail_count": 0,
            "last_duration_seconds": 10.0,
            "latest_run": dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
            "pass_count": 5,
            "skip_count": 0,
        },
    ]

    backfill_test_rollups(
        start_date="1970-01-02",
        end_date="1970-01-04",
    )

    rollups = DailyTestRollup.objects.all()

    assert [
        {
            "date": r.date,
            "pass_count": r.pass_count,
            "skip_count": r.skip_count,
            "fail_count": r.fail_count,
            "flaky_fail_count": r.flaky_fail_count,
            "last_duration_seconds": r.last_duration_seconds,
            "avg_duration_seconds": r.avg_duration_seconds,
            "latest_run": r.latest_run,
        }
        for r in rollups
    ] == [
        {
            "avg_duration_seconds": 1.0,
            "date": dt.date(1970, 1, 5),
            "fail_count": 10,
            "flaky_fail_count": 0,
            "last_duration_seconds": 10.0,
            "latest_run": dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
            "pass_count": 5,
            "skip_count": 0,
        },
        {
            "avg_duration_seconds": 10.0,
            "date": dt.date(1970, 1, 3),
            "fail_count": 1,
            "flaky_fail_count": 1,
            "last_duration_seconds": 10.0,
            "latest_run": dt.datetime.fromisoformat("1970-01-03T00:00:00Z"),
            "pass_count": 0,
            "skip_count": 0,
        },
    ]

    assert len(rollups[1].commits_where_fail) == 1

    backfill_test_rollups(
        start_date="1970-01-02",
        end_date="1970-01-05",
    )

    rollups = DailyTestRollup.objects.all()

    assert [
        {
            "date": r.date,
            "pass_count": r.pass_count,
            "skip_count": r.skip_count,
            "fail_count": r.fail_count,
            "flaky_fail_count": r.flaky_fail_count,
            "last_duration_seconds": r.last_duration_seconds,
            "avg_duration_seconds": r.avg_duration_seconds,
            "latest_run": r.latest_run,
        }
        for r in rollups
    ] == [
        {
            "avg_duration_seconds": 10.0,
            "date": dt.date(1970, 1, 3),
            "fail_count": 1,
            "flaky_fail_count": 1,
            "last_duration_seconds": 10.0,
            "latest_run": dt.datetime.fromisoformat("1970-01-03T00:00:00Z"),
            "pass_count": 0,
            "skip_count": 0,
        },
        {
            "avg_duration_seconds": 10000.0,
            "date": dt.date(1970, 1, 5),
            "fail_count": 1,
            "flaky_fail_count": 1,
            "last_duration_seconds": 10000.0,
            "latest_run": dt.datetime.fromisoformat("1970-01-05T00:00:00Z"),
            "pass_count": 0,
            "skip_count": 0,
        },
    ]

    for r in rollups:
        assert len(r.commits_where_fail) == 1
