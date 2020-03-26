import logging
from datetime import datetime
from typing import Sequence

import sqlalchemy.orm
from celery_config import pulls_task_name, notify_task_name, task_default_queue
from redis.exceptions import LockError

from database.models import Repository, Commit
from services.redis import get_redis_connection
from services.repository import (
    get_repo_provider_service,
    fetch_and_update_pull_request_information,
    EnrichedPull,
)
from services.notification.changes import get_changes
from services.yaml.reader import read_yaml_field
from services.report import ReportService
from tasks.base import BaseCodecovTask
from app import celery_app


log = logging.getLogger(__name__)


class PullSyncTask(BaseCodecovTask):

    """
        This is the task that syncs pull with the information the Git Provider gives us

    The most characteristic piece of this task is that it centers around the PR.
        We receive a (repoid, pullid) pair. And we fetch all the information
            from the git provider to update it as needed.

        This mostly includes
            - Updating basic database fields around the PR, like author
            - Updating `base` and `head` of the PR
            - Updating the `diff` and `flare` information of the PR using the `report` of its head
            - Updating all the commits that point to this pull in case the pull is being merged
            - Clear the caches we have around this PR

        At the end we call the notify task to do notifications with the new information we have
    """

    name = pulls_task_name

    async def run_async(
        self,
        db_session: sqlalchemy.orm.Session,
        *,
        repoid: int = None,
        pullid: int = None,
        **kwargs,
    ):
        redis_connection = get_redis_connection()
        lock_name = f"pullsync_{repoid}_{pullid}"
        try:
            with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=5):
                return await self.run_async_within_lock(
                    db_session, redis_connection, repoid=repoid, pullid=pullid, **kwargs
                )
        except LockError:
            log.info(
                "Unable to acquire PullSync lock. Not retrying because pull is being synced already",
                lock_name,
                extra=dict(pullid=pullid, repoid=repoid),
            )
            return {
                "notifier_called": False,
                "commit_updates_done": {'merged_count': 0, 'soft_deleted_count': 0},
                "pull_updated": False,
            }

    async def run_async_within_lock(
        self,
        db_session: sqlalchemy.orm.Session,
        redis_connection,
        *,
        repoid: int = None,
        pullid: int = None,
        **kwargs,
    ):
        repository = db_session.query(Repository).filter_by(repoid=repoid).first()
        assert repository
        repository_service = get_repo_provider_service(repository)
        current_yaml = repository.yaml
        enriched_pull = await fetch_and_update_pull_request_information(
            repository_service, db_session, repoid, pullid, current_yaml
        )
        pull = enriched_pull.database_pull
        if pull is None:
            log.info(
                "Not syncing pull since we can't find it in the database nor in the provider",
                extra=dict(pullid=pullid, repoid=repoid),
            )
            return {
                "notifier_called": False,
                "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
                "pull_updated": False,
            }
        report_service = ReportService()
        head_commit = pull.get_head_commit()
        if head_commit is None:
            log.info(
                "Not syncing pull since there is no head in our database",
                extra=dict(pullid=pullid, repoid=repoid),
            )
            return {
                "notifier_called": True,
                "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
                "pull_updated": False,
            }
        compared_to = pull.get_comparedto_commit()
        head_report = report_service.build_report_from_commit(head_commit)
        if compared_to is not None:
            base_report = report_service.build_report_from_commit(compared_to)
        else:
            base_report = None
        compare_dict = await repository_service.get_compare(
            pull.base, pull.head, with_commits=False
        )
        diff = compare_dict["diff"]
        changes = get_changes(base_report, head_report, diff)
        if head_report:
            color = read_yaml_field(current_yaml, ("coverage", "range"))
            pull.diff = head_report.apply_diff(diff)
            pull.flare = (
                head_report.flare(changes, color=color) if head_report else None
            )
        commits = await repository_service.get_pull_request_commits(pull.pullid)
        commit_updates_done = self.update_pull_commits(enriched_pull, commits)
        self.app.tasks[notify_task_name].apply_async(
            queue=task_default_queue, kwargs=dict(repoid=repoid, commitid=pull.head,)
        )
        self.clear_pull_related_caches(redis_connection, enriched_pull)
        return {
            "notifier_called": True,
            "commit_updates_done": commit_updates_done,
            "pull_updated": True,
        }

    def clear_pull_related_caches(self, redis_connection, enriched_pull: EnrichedPull):
        pull = enriched_pull.database_pull
        pull_dict = enriched_pull.provider_pull
        repository = pull.repository
        key = ":".join((repository.service, repository.owner.username, repository.name))
        if pull.state == "merged":
            base_branch = pull_dict["base"]["branch"]
            if base_branch:
                redis_connection.hdel("badge", (f"{key}:{base_branch}").lower())
                if base_branch == repository.branch:
                    redis_connection.hdel("badge", (f"{key}:").lower())

    def update_pull_commits(
        self, enriched_pull: EnrichedPull, commits: Sequence
    ) -> dict:
        """Updates commits considering what the new PR situation is.

            For example, if a pull is merged, it makes sense that their commits switch to
                `merged` mode and start being part of the `base` branch.

            This might be a problem when customers do squash merge, but it is somehow
                needed when the users do FastForward merge, since nothing else will update
                commit branches

        Args:
            enriched_pull (EnrichedPull): The pull that changed state
            commits (Sequence): The commits we might want to update
        
        Returns:
            dict: A dict of the changes that were made
        """
        pull = enriched_pull.database_pull
        pull_dict = enriched_pull.provider_pull
        repoid = pull.repoid
        pullid = pull.pullid
        db_session = pull.get_db_session()
        merged_count, deleted_count = 0, 0
        if commits:
            commits.append(pull.base)
            commits.append(pull.head)
            if pull.state == "merged":
                # merge the branch in
                merged_count = (
                    db_session.query(Commit)
                    .filter(
                        Commit.repoid == repoid,
                        Commit.pullid == pullid,
                        Commit.commitid.in_(commits),
                        ~Commit.merged,
                    )
                    .update(
                        {
                            Commit.branch: pull_dict["base"]["branch"],
                            Commit.updatestamp: datetime.now(),
                            Commit.merged: True,
                            Commit.deleted: False,
                        },
                        synchronize_session=False,
                    )
                )

            # set the rest of the commits to deleted (do not show in the UI)
            deleted_count = (
                db_session.query(Commit)
                .filter(
                    Commit.repoid == repoid,
                    Commit.pullid == pullid,
                    ~Commit.commitid.in_(commits),
                )
                .update({Commit.deleted: True}, synchronize_session=False)
            )
        return {"soft_deleted_count": deleted_count, "merged_count": merged_count}


RegisteredPullSyncTask = celery_app.register_task(PullSyncTask())
pull_sync_task = celery_app.tasks[RegisteredPullSyncTask.name]
