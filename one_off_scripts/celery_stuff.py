from datetime import datetime

from celery import Celery, signature
from shared.celery_config import BaseCeleryConfig

celery_app = Celery("tasks")
celery_app.config_from_object("shared.celery_config:BaseCeleryConfig")

default_task_name = BaseCeleryConfig.task_default_queue


def create_signature(name, args=None, kwargs=None, immutable=False):
    queue_name = default_task_name
    headers = dict(created_timestamp=datetime.now().isoformat())
    return signature(
        name,
        args=args,
        kwargs=kwargs,
        app=celery_app,
        queue=queue_name,
        headers=headers,
        immutable=immutable,
    )
