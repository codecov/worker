from celery import Celery

celery_app = Celery(
    'tasks',
    backend='redis://',
    broker='redis://guest@localhost:6379//'
)
