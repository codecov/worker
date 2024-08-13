import contextlib
from typing import Generator

from sqlalchemy.orm import Session

from app import celery_app


@contextlib.contextmanager
def run_tasks() -> Generator[None, None, None]:
    prev = celery_app.conf.task_always_eager
    celery_app.conf.update(task_always_eager=True)
    try:
        yield
    finally:
        celery_app.conf.update(task_always_eager=prev)


GLOBALS_USING_SESSION = [
    "celery_task_router.get_db_session",
    "database.engine.get_db_session",
    "tasks.base.get_db_session",
]


def hook_session(mocker, dbsession: Session):
    """
    This patches various module-local imports related to `get_db_session`.
    """
    mocker.patch("shared.metrics")
    for path in GLOBALS_USING_SESSION:
        mocker.patch(path, return_value=dbsession)


GLOBALS_USING_REPO_PROVIDER = [
    "tasks.notify.get_repo_provider_service",
    "tasks.upload_processor.get_repo_provider_service",
    "tasks.upload.get_repo_provider_service",
]


def hook_repo_provider(mocker, mock_repo_provider):
    """
    Hooks / mocks various `get_repo_provider_service` locals.
    Due to how import resolution works in python, we have to patch this
    *everywhere* that is *imported* into, instead of patching the function where
    it is defined.
    The reason is that imports are resolved at import time, and overriding the
    function definition after the fact does not work.
    """
    for path in GLOBALS_USING_REPO_PROVIDER:
        mocker.patch(path, return_value=mock_repo_provider)
