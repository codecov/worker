from celery import Celery
import celery_config


celery_app = Celery('tasks')
celery_app.config_from_object(celery_config)
