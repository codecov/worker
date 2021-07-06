from datetime import datetime, timezone
from helpers.clock import get_utc_now, get_utc_now_as_iso_format


def test_get_utc_now():
    res = get_utc_now()
    assert isinstance(res, datetime)
    assert res.tzinfo == timezone.utc


def test_get_utc_now_as_iso_format():
    res = get_utc_now_as_iso_format()
    assert isinstance(res, str)
    assert isinstance(datetime.fromisoformat(res), datetime)
