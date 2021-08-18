import logging
import logging.config

from celery import Celery

from helpers.logging_config import get_logging_config_dict
from helpers.sentry import initialize_sentry, is_sentry_enabled

log = logging.getLogger(__name__)


_config_dict = get_logging_config_dict()
logging.config.dictConfig(_config_dict)

if is_sentry_enabled():
    initialize_sentry()

celery_app = Celery("tasks")
celery_app.config_from_object("celery_config:CeleryWorkerConfig")
