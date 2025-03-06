from datetime import datetime, timezone


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_utc_now_as_iso_format() -> str:
    return get_utc_now().isoformat()


def get_seconds_to_next_hour() -> int:
    now = datetime.now(timezone.utc)
    current_seconds = (now.minute * 60) + now.second
    return 3600 - current_seconds
