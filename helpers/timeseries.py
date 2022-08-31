from shared.config import get_config


def timeseries_enabled() -> bool:
    return get_config("setup", "timeseries", "enabled", default=False)


def backfill_max_batch_size() -> int:
    return get_config("setup", "timeseries", "backfill_max_batch_size", default=500)
