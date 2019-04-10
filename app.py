import logging.config

from celery import Celery

import celery_config
from logging_config import config_dict

celery_app = Celery('tasks')
celery_app.config_from_object(celery_config)
logging.config.dictConfig(config_dict)
