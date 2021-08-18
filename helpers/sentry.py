import os

import sentry_sdk
from celery.exceptions import SoftTimeLimitExceeded
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from shared.config import get_config

from helpers.version import get_current_version


def before_send(event, hint):
    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]
        if isinstance(exc_value, SoftTimeLimitExceeded):
            return None
    return event


def is_sentry_enabled() -> bool:
    return bool(get_config("services", "sentry", "server_dsn"))


def initialize_sentry() -> None:
    version = get_current_version()
    version_str = f"worker-{version}"
    sentry_dsn = get_config("services", "sentry", "server_dsn")
    sentry_sdk.init(
        sentry_dsn,
        before_send=before_send,
        sample_rate=float(os.getenv("SENTRY_PERCENTAGE", 1.0)),
        integrations=[CeleryIntegration(), SqlalchemyIntegration(), RedisIntegration()],
        release=version_str,
    )
