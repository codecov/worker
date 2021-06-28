from datetime import datetime, timezone


def get_utc_now() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def get_utc_now_as_iso_format() -> str:
    return get_utc_now().isoformat()
