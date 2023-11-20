import logging

from celery.exceptions import SoftTimeLimitExceeded
from openai import AsyncOpenAI
from shared.config import get_config
from shared.torngit.base import TokenType
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Repository
from helpers.exceptions import RepositoryWithoutValidBotError
from services.ai_pr_review import perform_review
from services.repository import get_repo_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class AiPrReviewTask(BaseCodecovTask, name="app.tasks.ai_pr_review.AiPrReview"):
    throws = (SoftTimeLimitExceeded,)

    async def run_async(
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
            await perform_review(repository, pullid)
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
