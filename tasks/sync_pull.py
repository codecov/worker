import json
import logging
import os
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Sequence

import sqlalchemy.orm
from asgiref.sync import async_to_sync
from redis.exceptions import LockError
from shared.celery_config import notify_task_name, pulls_task_name
from shared.metrics import Counter, Histogram
from shared.reports.types import Change
from shared.torngit.exceptions import TorngitClientError
from shared.yaml import UserYaml
from shared.yaml.user_yaml import OwnerContext

from app import celery_app
from database.models import Commit, Pull, Repository
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.metrics import metrics
from rollouts import SYNC_PULL_LOCK_TIMEOUT
from services.comparison.changes import get_changes
from services.redis import get_redis_connection
from services.report import Report, ReportService
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information,
    get_repo_provider_service,
)
from services.yaml.reader import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

TASK_RUN_COUNT = Counter(
    "sync_pull_task_run_count",
    "Number of SyncPull tasks that were executed (per wait group)",
    ["wait_group"],
)

TASK_REJECTED_COUNT = Counter(
    "sync_pull_task_rejected_count",
    "Number of SyncPull tasks that were _not_ executed because they couldn't get a lock (per wait group)",
    ["wait_group"],
)

TIME_FOR_LOCK_HISTOGRAM = Histogram(
    "sync_pull_time_to_get_lock",
    "Distribution of the time a SyncPull task was waiting for the lock (per wait group)",
    ["wait_group"],
    unit="milliseconds",
    buckets=[
        100,
        200,
        300,
        400,
        500,
        600,
        700,
        800,
        900,
        1000,
        2000,
        3000,
        4000,
        5000,
        6000,
        10000,
    ],
)


class PullSyncTask(BaseCodecovTask, name=pulls_task_name):
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

    def run_impl(
        self,
        db_session: sqlalchemy.orm.Session,
        *,
        repoid: int = None,
        pullid: int = None,
        should_send_notifications: bool = True,
        **kwargs,
    ):
        redis_connection = get_redis_connection()
        pullid = int(pullid)
        repoid = int(repoid)
        lock_name = f"pullsync_{repoid}_{pullid}"
        wait_for_lock_timeout_seconds, metrics_tag = SYNC_PULL_LOCK_TIMEOUT.check_value(
            identifier=repoid, default=(5, "long_timeout")
        )
        start_wait = time.monotonic()
        try:
            with redis_connection.lock(
                lock_name,
                timeout=60 * 5,
                blocking_timeout=wait_for_lock_timeout_seconds,
            ):
                TASK_RUN_COUNT.labels(wait_group=metrics_tag).inc()
                time_to_get_lock_seconds = time.monotonic() - start_wait
                TIME_FOR_LOCK_HISTOGRAM.labels(wait_group=metrics_tag).observe(
                    time_to_get_lock_seconds * 1000
                )
                return self.run_impl_within_lock(
                    db_session,
                    redis_connection,
                    repoid=repoid,
                    pullid=pullid,
                    should_send_notifications=should_send_notifications,
                    **kwargs,
                )
        except LockError:
            log.info(
                "Unable to acquire PullSync lock. Not retrying because pull is being synced already",
                extra=dict(pullid=pullid, repoid=repoid),
            )
            TASK_REJECTED_COUNT.labels(wait_group=metrics_tag).inc()
            return {
                "notifier_called": False,
                "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
                "pull_updated": False,
                "reason": "unable_fetch_lock",
            }

    def run_impl_within_lock(
        self,
        db_session: sqlalchemy.orm.Session,
        redis_connection,
        *,
        repoid: int = None,
        pullid: int = None,
        should_send_notifications: bool = True,
        **kwargs,
    ):
        commit_updates_done = {"merged_count": 0, "soft_deleted_count": 0}
        repository = db_session.query(Repository).filter_by(repoid=repoid).first()
        assert repository
        try:
            installation_name_to_use = get_installation_name_for_owner_for_task(
                db_session, self.name, repository.owner
            )
            repository_service = get_repo_provider_service(
                repository, installation_name_to_use=installation_name_to_use
            )
        except RepositoryWithoutValidBotError:
            log.warning(
                "Could not sync pull because there is no valid bot found for that repo",
                extra=dict(pullid=pullid, repoid=repoid),
                exc_info=True,
            )
            return {
                "notifier_called": False,
                "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
                "pull_updated": False,
                "reason": "no_bot",
            }
        context = OwnerContext(
            owner_onboarding_date=repository.owner.createstamp,
            owner_plan=repository.owner.plan,
            ownerid=repository.ownerid,
        )
        current_yaml = UserYaml.get_final_yaml(
            owner_yaml=repository.owner.yaml,
            repo_yaml=repository.yaml,
            owner_context=context,
        )
        with metrics.timer(f"{self.metrics_prefix}.fetch_pull"):
            enriched_pull = async_to_sync(fetch_and_update_pull_request_information)(
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
                "reason": "no_db_pull",
            }
        if enriched_pull.provider_pull is None:
            log.info(
                "Not syncing pull since we can't find it in the provider. There is nothing to sync",
                extra=dict(pullid=pullid, repoid=repoid),
            )
            return {
                "notifier_called": False,
                "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
                "pull_updated": False,
                "reason": "not_in_provider",
            }
        self.trigger_ai_pr_review(enriched_pull, current_yaml)
        report_service = ReportService(
            current_yaml, gh_app_installation_name=installation_name_to_use
        )
        head_commit = pull.get_head_commit()
        if head_commit is None:
            log.info(
                "Not syncing pull since there is no head in our database",
                extra=dict(pullid=pullid, repoid=repoid),
            )
            return {
                "notifier_called": False,
                "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
                "pull_updated": False,
                "reason": "no_head",
            }
        compared_to = pull.get_comparedto_commit()
        head_report = report_service.get_existing_report_for_commit(head_commit)
        if compared_to is not None:
            base_report = report_service.get_existing_report_for_commit(compared_to)
        else:
            base_report = None
        commits = None
        db_session.commit()
        try:
            commits = async_to_sync(repository_service.get_pull_request_commits)(
                pull.pullid
            )
            base_ancestors_tree = async_to_sync(repository_service.get_ancestors_tree)(
                enriched_pull.provider_pull["base"]["branch"]
            )
            commit_updates_done = self.update_pull_commits(
                enriched_pull, commits, base_ancestors_tree
            )
            db_session.commit()
        except TorngitClientError:
            log.warning(
                "Unable to fetch information about pull commits",
                extra=dict(pullid=pullid, repoid=repoid),
            )
        self.update_pull_from_reports(
            pull, repository_service, base_report, head_report, current_yaml
        )
        db_session.commit()
        notifier_was_called = False
        if should_send_notifications:
            notifier_was_called = True
            self.app.tasks[notify_task_name].apply_async(
                kwargs=dict(repoid=repoid, commitid=pull.head)
            )
        self.clear_pull_related_caches(redis_connection, enriched_pull)
        return {
            "notifier_called": notifier_was_called,
            "commit_updates_done": commit_updates_done,
            "pull_updated": True,
            "reason": "success",
        }

    def cache_changes(self, pull: Pull, changes: List[Change]):
        """
        Caches the list of files with changes for a given comparison.
        This information will be used API-side to speed up responses.
        """
        owners_with_cached_changes = [
            int(ownerid.strip())
            for ownerid in os.getenv("OWNERS_WITH_CACHED_CHANGES", "").split(",")
            if ownerid != ""
        ]
        if pull.repository.owner.ownerid in owners_with_cached_changes:
            log.info(
                "Caching files with changes",
                extra=dict(pullid=pull.pullid, repoid=pull.repoid),
            )
            redis = get_redis_connection()
            key = "/".join(
                (
                    "compare-changed-files",
                    pull.repository.owner.service,
                    pull.repository.owner.username,
                    pull.repository.name,
                    f"{pull.pullid}",
                )
            )
            redis.set(
                key,
                json.dumps([change.path for change in changes]),
                ex=86400,  # 1 day in seconds
            )
            log.info(
                "Finished caching files with changes",
                extra=dict(pullid=pull.pullid, repoid=pull.repoid),
            )

    def update_pull_from_reports(
        self,
        pull: Pull,
        repository_service,
        base_report: Report,
        head_report: Report,
        current_yaml,
    ):
        try:
            compare_dict = async_to_sync(repository_service.get_compare)(
                pull.base, pull.head, with_commits=False
            )
            diff = compare_dict["diff"]
            changes = get_changes(base_report, head_report, diff)
            if changes:
                self.cache_changes(pull, changes)
            if head_report:
                color = read_yaml_field(current_yaml, ("coverage", "range"))
                pull.diff = head_report.apply_diff(diff)
                pull.flare = (
                    head_report.flare(changes, color=color) if head_report else None
                )
            return True
        except TorngitClientError:
            log.warning(
                "Unable to fetch information about diff",
                extra=dict(pullid=pull.pullid, repoid=pull.repoid),
            )
            return False

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
        self,
        enriched_pull: EnrichedPull,
        commits_on_pr: Sequence,
        ancestors_tree_on_base: Dict[str, Any],
    ) -> dict:
        """Updates commits considering what the new PR situation is.

            For example, if a pull is merged, it makes sense that their commits switch to
                `merged` mode and start being part of the `base` branch.

            On squash merge we have a bit of an issue, since we can't move the commits to the
                new branch (they didn't go there), but they don't go deleted. So they just hang
                there for a while. Theoretically a branch deletion should trigger something
                and the system will deal with those commits, but I dont think this is implemented
                yet

        Args:
            enriched_pull (EnrichedPull): The pull that changed state
            commits_on_pr (Sequence): The commits that were on the PR we might want to update
            ancestors_tree_on_base (Dict[str, Any]): Ancestor tree of commits starting at the base

        Returns:
            dict: A dict of the changes that were made
        """
        pull = enriched_pull.database_pull
        pull_dict = enriched_pull.provider_pull
        repoid = pull.repoid
        pullid = pull.pullid
        db_session = pull.get_db_session()
        merged_count, deleted_count = 0, 0
        if commits_on_pr:
            if pull.state == "merged":
                is_squash_merge = self.was_pr_merged_with_squash(
                    commits_on_pr, ancestors_tree_on_base
                )
                if not is_squash_merge:
                    log.info(
                        "Moving commits to base branch",
                        extra=dict(
                            commits_on_pr=commits_on_pr,
                            repoid=repoid,
                            pullid=pullid,
                            new_branch=pull_dict["base"]["branch"],
                        ),
                    )
                    merged_count = (
                        db_session.query(Commit)
                        .filter(
                            Commit.repoid == repoid,
                            Commit.pullid == pullid,
                            Commit.commitid.in_(commits_on_pr + [pull.base, pull.head]),
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
                    ~Commit.commitid.in_(commits_on_pr + [pull.base, pull.head]),
                )
                .update({Commit.deleted: True}, synchronize_session=False)
            )
        return {"soft_deleted_count": deleted_count, "merged_count": merged_count}

    def was_pr_merged_with_squash(
        self, commits_on_pr: Sequence[str], base_ancestors_tree: Dict[str, Any]
    ) -> bool:
        """
            Determines if commit was merged with squash merge or not, by looking at the commits
                that were on the commit and the commits that are on the base branch now

            The logic here is that, if at least one commit of the PR made it into the base branch,
                then we know no ways of merging just that one commit without the other ones. So it
                is probable that the commit was merged with merge-commit (or some other strategy
                that moves all commits to the base branch).

            Notice that the reason we don't require all commits to be on the base branch now is
                because it's possible that the base branch moves so fast that by the time
                we check it part of the PR commits could have been merged via merge-commit, but
                are already out of the first page of commit listing.

            This also brings us the the limitation of this logic: if the base branch moves so fast
                that ALL the commits are out of the first page of listing when we check, we
                will assume (wrongly) that this was a squash commit

        Args:
            commits_on_pr (Sequence[str]): Description
            base_ancestors_tree (Dict[str, Any]): Description
        """
        commits_on_pr_set = set(commits_on_pr)
        current_level = deque([base_ancestors_tree])
        while current_level:
            el = current_level.popleft()
            if el["commitid"] in commits_on_pr_set:
                log.info(
                    "Commit currently on base tree was also on PR. Calling it a normal merge",
                    extra=dict(
                        commits_on_pr=commits_on_pr,
                        commit_on_base=el["commitid"],
                        base_head=base_ancestors_tree["commitid"],
                    ),
                )
                return False
            for p in el.get("parents", []):
                current_level.append(p)
        log.info(
            "Commits from PR not found on base tree. Calling it a squash merge",
            extra=dict(
                commits_on_pr=commits_on_pr, base_head=base_ancestors_tree["commitid"]
            ),
        )
        return True

    def trigger_ai_pr_review(self, enriched_pull: EnrichedPull, current_yaml: UserYaml):
        pull = enriched_pull.database_pull
        if pull.state == "open" and read_yaml_field(
            current_yaml, ("ai_pr_review", "enabled"), False
        ):
            review_method = read_yaml_field(
                current_yaml, ("ai_pr_review", "method"), "auto"
            )
            label_name = read_yaml_field(
                current_yaml, ("ai_pr_review", "label_name"), None
            )
            pull_labels = enriched_pull.provider_pull.get("labels", [])
            if review_method == "auto" or (
                review_method == "label" and label_name in pull_labels
            ):
                log.info(
                    "Triggering AI PR review task",
                    extra=dict(
                        repoid=pull.repoid,
                        pullid=pull.pullid,
                        review_method=review_method,
                        lbale_name=label_name,
                        pull_labels=pull_labels,
                    ),
                )
                self.app.tasks["app.tasks.ai_pr_review.AiPrReview"].apply_async(
                    kwargs=dict(repoid=pull.repoid, pullid=pull.pullid)
                )


RegisteredPullSyncTask = celery_app.register_task(PullSyncTask())
pull_sync_task = celery_app.tasks[RegisteredPullSyncTask.name]
