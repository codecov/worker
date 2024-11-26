import logging
from datetime import datetime, timezone

from shared.celery_config import commit_update_task_name
from shared.torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError

from app import celery_app
from database.models import Branch, Commit, Pull
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from services.repository import (
    get_repo_provider_service,
    possibly_update_commit_from_provider_info,
)
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


def standardize_datetime(dt):
    """Ensure a datetime is offset-aware and in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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

            if isinstance(commit.timestamp, str):
                log.warning(
                    "Commit Update Task: commit.timestamp is a str",
                    extra=dict(commitid=commitid, repoid=repoid),
                )
                commit.timestamp = datetime.fromisoformat(commit.timestamp)

            if commit.pullid is not None:
                # upsert pull
                pull = (
                    db_session.query(Pull)
                    .filter(Pull.repoid == repoid, Pull.pullid == commit.pullid)
                    .first()
                )

                if pull is None:
                    pull = Pull(
                        repoid=repoid,
                        pullid=commit.pullid,
                        author_id=commit.author_id,
                        head=commit.commitid,
                    )
                    db_session.add(pull)
                else:
                    previous_pull_head = (
                        db_session.query(Commit)
                        .filter(Commit.repoid == repoid, Commit.commitid == pull.head)
                        .first()
                    )
                    if (
                        previous_pull_head is None
                        or previous_pull_head.deleted == True
                        or standardize_datetime(previous_pull_head.timestamp)
                        < standardize_datetime(commit.timestamp)
                    ):
                        pull.head = commit.commitid

            if commit.branch is not None:
                # upsert branch
                branch = (
                    db_session.query(Branch)
                    .filter(Branch.repoid == repoid, Branch.branch == commit.branch)
                    .first()
                )

                if branch is None:
                    branch = Branch(
                        repoid=repoid,
                        branch=commit.branch,
                        head=commit.commitid,
                        authors=[commit.author_id],
                    )
                    db_session.add(branch)
                else:
                    if commit.author_id is not None:
                        if branch.authors is None:
                            branch.authors = [commit.author_id]
                        elif commit.author_id not in branch.authors:
                            branch.authors.append(commit.author_id)

                    previous_branch_head = (
                        db_session.query(Commit)
                        .filter(Commit.repoid == repoid, Commit.commitid == branch.head)
                        .first()
                    )

                    if (
                        previous_branch_head is None
                        or previous_branch_head.deleted == True
                        or previous_branch_head.timestamp < commit.timestamp
                    ):
                        branch.head = commit.commitid

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
