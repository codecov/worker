import logging
from typing import Any, Literal

from redis import Redis
from redis.exceptions import LockError
from shared.celery_config import process_flakes_task_name
from sqlalchemy.orm import Session

from app import celery_app
from services.processing.flake_processing import process_flake_for_repo_commit
from services.redis import get_redis_connection
from services.test_analytics.ta_process_flakes import process_flakes_for_repo
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


FLAKE_EXPIRY_COUNT = 30
LOCK_NAME = "flake_lock:{}"
NEW_KEY = "flake_uploads_list:{}"
OLD_KEY = "flake_uploads:{}"


def get_redis_val(redis_client: Redis, repo_id: int) -> tuple[list[bytes], bool]:
    commit_ids = redis_client.lpop(NEW_KEY.format(repo_id), 10)
    if commit_ids is None:
        commit_ids = []

    current_commit = False
    with redis_client.pipeline() as pipe:
        # can't use getdel because the value of the key is not a string
        pipe.get(OLD_KEY.format(repo_id))
        pipe.delete(OLD_KEY.format(repo_id))
        commit_id = pipe.execute()
        if commit_id[0] is not None:
            current_commit = True

    return commit_ids, current_commit


class ProcessFlakesTask(BaseCodecovTask, name=process_flakes_task_name):
    """
    This task is currently called in the test results finisher task and in the sync pulls task
    """

    def run_impl(
        self,
        _db_session: Session,
        *,
        repo_id: int,
        commit_id: str,
        impl_type: Literal["old", "new", "both"] = "old",
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

        if impl_type == "new" or impl_type == "both":
            process_flakes_for_repo(repo_id)
            if impl_type == "new":
                return {"successful": True}

        redis_client = get_redis_connection()
        lock_name = LOCK_NAME.format(repo_id)

        process_func = process_flake_for_repo_commit

        try:
            with redis_client.lock(
                lock_name,
                timeout=max(300, self.hard_time_limit_task),
                blocking_timeout=3,
            ):
                while True:
                    commit_ids, current_commit = get_redis_val(redis_client, repo_id)
                    if not commit_ids and not current_commit:
                        break

                    for commitid in commit_ids:
                        process_func(repo_id, commitid.decode())

                    if current_commit:
                        process_func(repo_id, commit_id)

        except LockError:
            log.warning("Unable to acquire process flakeslock for key %s.", lock_name)
            return {"successful": False}

        return {"successful": True}


RegisteredProcessFlakesTask = celery_app.register_task(ProcessFlakesTask())
process_flakes_task = celery_app.tasks[RegisteredProcessFlakesTask.name]
