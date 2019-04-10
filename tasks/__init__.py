from tasks.flush_repo import flush_repo
from tasks.upload import upload_task
from app import celery_app


@celery_app.task
def add(x, y):
    return x + y
