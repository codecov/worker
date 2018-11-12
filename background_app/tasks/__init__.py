from app import celery_app
from tasks.verify import verify_bot


@celery_app.task
def add(x, y):
    return x + y
