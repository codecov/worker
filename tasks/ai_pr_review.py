import logging

from asgiref.sync import async_to_sync
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Repository
from helpers.exceptions import RepositoryWithoutValidBotError
from services.ai_pr_review import perform_review
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class AiPrReviewTask(BaseCodecovTask, name="app.tasks.ai_pr_review.AiPrReview"):
    throws = (SoftTimeLimitExceeded,)

    def run_impl(
        self,
        db_session: Session,
        *,
        repoid: int,
        pullid: int,
        **kwargs,
    ):
        log.info("Starting AI PR review task", extra=dict(repoid=repoid, pullid=pullid))

        repository = db_session.query(Repository).filter_by(repoid=repoid).first()
        assert repository
        if repository.owner.service != "github":
            log.warning("AI PR review only supports GitHub currently")
            return {"successful": False, "error": "not_github"}

        try:
            async_to_sync(perform_review)(repository, pullid)
            return {"successful": True}
        except RepositoryWithoutValidBotError:
            log.warning(
                "No valid bot found for repo",
                extra=dict(pullid=pullid, repoid=repoid),
                exc_info=True,
            )
            return {"successful": False, "error": "no_bot"}


RegisteredAiPrReviewTask = celery_app.register_task(AiPrReviewTask())
ai_pr_view_task = celery_app.tasks[RegisteredAiPrReviewTask.name]
