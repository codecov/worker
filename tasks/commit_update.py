import logging

from shared.celery_config import commit_update_task_name
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitRepoNotFoundError,
)

from app import celery_app
from database.models import Commit
from helpers.exceptions import RepositoryWithoutValidBotError
from services.repository import (
    get_repo_provider_service,
    update_commit_from_provider_info,
)
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class CommitUpdateTask(BaseCodecovTask, name=commit_update_task_name):
    async def run_async(
        self,
        db_session,
        repoid: int,
        commitid: str,
        **kwargs,
    ):
        commit = None
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        repository = commit.repository
        repository_service = None
        was_updated = False
        try:
            repository_service = get_repo_provider_service(repository, commit)
            was_updated = await self.possibly_update_commit_from_provider_info(
                commit, repository_service
            )
        except RepositoryWithoutValidBotError:
            log.warning(
                "Unable to reach git provider because repo doesn't have a valid bot",
                extra=dict(repoid=repoid, commit=commitid),
            )
        except TorngitRepoNotFoundError:
            log.warning(
                "Unable to reach git provider because this specific bot/integration can't see that repository",
                extra=dict(repoid=repoid, commit=commitid),
            )
        except TorngitClientError:
            log.warning(
                "Unable to reach git provider because there was a 4xx error",
                extra=dict(repoid=repoid, commit=commitid),
                exc_info=True,
            )
        if was_updated:
            log.info(
                "Commit updated successfully",
                extra=dict(commitid=commitid, repoid=repoid),
            )
        return {"was_updated": was_updated}

    # TODO move this into services as it is used in upload task also
    async def possibly_update_commit_from_provider_info(
        self, commit, repository_service
    ):
        repoid = commit.repoid
        commitid = commit.commitid
        try:
            if not commit.message:
                log.info(
                    "Commit does not have all needed info. Reaching provider to fetch info",
                    extra=dict(repoid=repoid, commit=commitid),
                )
                await update_commit_from_provider_info(repository_service, commit)
                return True
        except TorngitObjectNotFoundError:
            log.warning(
                "Could not update commit with info because it was not found at the provider",
                extra=dict(repoid=repoid, commit=commitid),
            )
            return False
        log.debug(
            "Not updating commit because it already seems to be populated",
            extra=dict(repoid=repoid, commit=commitid),
        )
        return False


RegisteredCommitUpdateTask = celery_app.register_task(CommitUpdateTask())
commit_update_task = celery_app.tasks[RegisteredCommitUpdateTask.name]
