import logging
from typing import Any

from redis.exceptions import LockError
from shared.celery_config import process_flakes_task_name

from app import celery_app
from services.processing.flake_processing import process_flake_for_repo_commit
from services.redis import get_redis_connection
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


FLAKE_EXPIRY_COUNT = 30


class ProcessFlakesTask(BaseCodecovTask, name=process_flakes_task_name):
    """
    This task is currently called in the test results finisher task and in the sync pulls task
    """

    def run_impl(
        self,
        _db_session: Any,
        *,
        repo_id: int,
        commit_id: str,
        **kwargs: Any,
    ):
        """
        This task wants to iterate through uploads for a given commit that have yet to be
        "flake processed".

        For each of those uploads it wants to iterate through its test instances and
        update existing flakes' count, recent_passes_count, fail_count, and end_date fields
        depending on whether the test instance passed or failed.

        For each upload it wants to keep track of newly created flakes and keep those in a separate
        collection than the existing flakes, so at the end it can bulk create the new flakes and
        bulk update the existing flakes.

        It also wants to increment the flaky_fail_count of the relevant DailyTestRollup when it creates
        a new flake so it keeps track of those changes and bulk updates those as well.

        When it's done with an upload it merges the new flakes dictionary into the existing flakes dictionary
        and then clears the new flakes dictionary so the following upload considers the flakes created during the previous
        iteration as existing.

        The redis locking is to prevent mutliple instances of the task running at the same time for the same repo.
        The locking scheme is set up such that no upload will be unprocessed. Before queuing up the process flakes task the
        test results finisher and sync pulls tasks will set the flake_uploads key in redis for that repo.
        """
        log.info(
            "Received process flakes task",
            extra=dict(repoid=repo_id, commit=commit_id),
        )

        redis_client = get_redis_connection()
        lock_name = f"flake_lock:{repo_id}"
        try:
            with redis_client.lock(
                lock_name, timeout=max(300, self.hard_time_limit_task), blocking=False
            ):
                while redis_client.get(f"flake_uploads:{repo_id}") is not None:
                    redis_client.delete(f"flake_uploads:{repo_id}")
                    process_flake_for_repo_commit(repo_id, commit_id)
        except LockError:
            log.warning("Unable to acquire process flakeslock for key %s.", lock_name)
            return {"successful": False}

        return {"successful": True}


RegisteredProcessFlakesTask = celery_app.register_task(ProcessFlakesTask())
process_flakes_task = celery_app.tasks[RegisteredProcessFlakesTask.name]
