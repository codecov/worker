from shared.config import get_config


def backfill_max_batch_size() -> int:
    return get_config("setup", "timeseries", "backfill_max_batch_size", default=500)
