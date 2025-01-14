import logging

import sentry_sdk
from shared.django_apps.core.models import Repository

from app import celery_app
from database.engine import Session
from services.cleanup.cleanup import run_cleanup
from services.cleanup.utils import CleanupSummary
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class FlushRepoTask(BaseCodecovTask, name="app.tasks.flush_repo.FlushRepo"):
    @sentry_sdk.trace
    def run_impl(
        self, _db_session: Session, *, repoid: int, **kwargs
    ) -> CleanupSummary:
        log.info("Deleting repo contents", extra={"repoid": repoid})
        repo_query = Repository.objects.filter(repoid=repoid)

        summary = run_cleanup(repo_query)
        log.info("Deletion finished", extra={"repoid": repoid, "summary": summary})
        return summary


FlushRepo = celery_app.register_task(FlushRepoTask())
flush_repo = celery_app.tasks[FlushRepo.name]
