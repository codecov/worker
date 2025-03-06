from datetime import datetime, timezone

import pytest
from freezegun import freeze_time

from helpers.clock import (
    get_seconds_to_next_hour,
    get_utc_now,
    get_utc_now_as_iso_format,
)


def test_get_utc_now():
    res = get_utc_now()
    assert isinstance(res, datetime)
    assert res.tzinfo == timezone.utc


def test_get_utc_now_as_iso_format():
    res = get_utc_now_as_iso_format()
    assert isinstance(res, str)
    assert isinstance(datetime.fromisoformat(res), datetime)


@pytest.mark.parametrize(
    "timestamp, expected",
    [
        ("2024-04-22T10:22:00", 38 * 60),
        ("2024-04-22T10:22:59", 38 * 60 - 59),
        ("2024-04-22T10:59:59", 1),
        ("2024-04-22T10:59:00", 60),
    ],
)
def test_get_seconds_to_next_hour(timestamp, expected):
    with freeze_time(timestamp):
        assert get_seconds_to_next_hour() == expected
