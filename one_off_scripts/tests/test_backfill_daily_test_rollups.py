import datetime as dt

import pytest
from shared.django_apps.reports.models import DailyTestRollup

from one_off_scripts.backfill_daily_test_rollups import backfill_test_rollups
from one_off_scripts.tests.utils import setup_one_off_tests


@pytest.mark.django_db(transaction=True)
def test_backfill_test_rollups():
    setup_one_off_tests()

    rollups = DailyTestRollup.objects.all().order_by("date")
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

    rollups = DailyTestRollup.objects.all().order_by("date")

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
            "avg_duration_seconds": 1.0,
            "date": dt.date(1970, 1, 5),
            "fail_count": 10,
            "flaky_fail_count": 0,
            "last_duration_seconds": 10.0,
            "latest_run": dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
            "pass_count": 5,
            "skip_count": 0,
        },
    ]

    assert len(rollups[0].commits_where_fail) == 1

    backfill_test_rollups(
        start_date="1970-01-02",
        end_date="1970-01-05",
    )

    rollups = DailyTestRollup.objects.all().order_by("date")

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
