import pytest

from helpers.health_check import (
    HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS,
    get_health_check_interval_seconds,
)


@pytest.mark.parametrize(
    "input,expected",
    [
        (-10, HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS),
        (0, HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS),
        (None, HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS),
        ("batata", HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS),
        (20, 20),
        ("5", 5),
    ],
)
def test_get_interval_seconds(mock_configuration, input, expected):
    mock_configuration.set_params(
        {"setup": {"tasks": {"healthcheck": {"interval_seconds": input}}}}
    )
    interval = get_health_check_interval_seconds()
    assert interval == expected
