from shared.config import get_config


def timeseries_enabled() -> bool:
    return get_config("setup", "timeseries", "enabled", default=False)


def backfill_batch_size() -> int:
    return int(get_config("setup", "timeseries", "backfill_batch_size", default=100))
