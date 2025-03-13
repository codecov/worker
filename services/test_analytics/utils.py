import mmh3
from shared.config import get_config


def should_use_timeseries(repoid: int) -> bool:
    timeseries_enabled = get_config("setup", "timeseries", "enabled", default=False)
    if timeseries_enabled:
        return True
    return False


def calc_test_id(name: str, classname: str, testsuite: str) -> bytes:
    h = mmh3.mmh3_x64_128()  # assumes we're running on x64 machines
    h.update(testsuite.encode("utf-8"))
    h.update(classname.encode("utf-8"))
    h.update(name.encode("utf-8"))
    test_id_hash = h.digest()

    return test_id_hash
