from app import celery_app


class BaseCodecovTask(celery_app.Task):
    pass
