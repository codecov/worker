import logging

from shared.config import get_config

HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS = 10

logger = logging.getLogger(__name__)


def get_health_check_interval_seconds():
    try:
        interval_config = int(
            get_config(
                "setup",
                "tasks",
                "healthcheck",
                "interval_seconds",
                default=HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS,
            )
        )
        if interval_config >= 1:
            return interval_config
    except (ValueError, TypeError):
        logger.warning(
            "Invalid configuration for healthcheck interval. Using default value of 10s"
        )
    return HEALTH_CHECK_DEFAULT_INTERVAL_SECONDS
