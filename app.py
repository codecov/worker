import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from celery import Celery

import celery_config
from covreports.config import get_config

sentry_dsn = get_config("services", "sentry", "server_dsn")
if sentry_dsn:
    sentry_sdk.init(
        sentry_dsn,
        integrations=[CeleryIntegration(), SqlalchemyIntegration(), RedisIntegration()],
    )


celery_app = Celery("tasks")
celery_app.config_from_object(celery_config)
