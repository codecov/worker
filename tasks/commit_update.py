import logging

from shared.celery_config import commit_update_task_name
from shared.torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError

from app import celery_app
from database.models import Commit
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from services.repository import (
    get_repo_provider_service,
    possibly_update_commit_from_provider_info,
)
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class CommitUpdateTask(BaseCodecovTask, name=commit_update_task_name):
    def run_impl(
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
            installation_name_to_use = get_installation_name_for_owner_for_task(
                self.name, repository.owner
            )
            repository_service = get_repo_provider_service(
                repository, installation_name_to_use=installation_name_to_use
            )
            was_updated = possibly_update_commit_from_provider_info(
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


RegisteredCommitUpdateTask = celery_app.register_task(CommitUpdateTask())
commit_update_task = celery_app.tasks[RegisteredCommitUpdateTask.name]
