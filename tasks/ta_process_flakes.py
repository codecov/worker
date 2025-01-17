import logging
from typing import Any

from redis.exceptions import LockError
from shared.django_apps.reports.models import CommitReport, ReportSession
from shared.utils.enums import TaskConfigGroup

from app import celery_app
from django_scaffold import settings
from services.redis import get_redis_connection
from ta_storage.bq import BQDriver
from ta_storage.pg import PGDriver
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

TA_FLAKE_LOCK_KEY = "ta_flake_lock:{repo_id}"
TA_FLAKE_UPLOADS_KEY = "ta_flake_uploads:{repo_id}"

FLAKE_EXPIRY_COUNT = 30

ta_process_flakes_task_name = (
    f"app.tasks.{TaskConfigGroup.flakes.value}.TAProcessFlakesTask"
)


class TAProcessFlakesTask(BaseCodecovTask, name=ta_process_flakes_task_name):
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
        log.info(
            "Received process flakes task",
            extra=dict(repoid=repo_id, commit=commit_id),
        )

        redis_client = get_redis_connection()
        lock_name = f"ta_flake_lock:{repo_id}"
        try:
            with redis_client.lock(
                lock_name, timeout=max(300, self.hard_time_limit_task), blocking=False
            ):
                while redis_client.get(f"ta_flake_uploads:{repo_id}") is not None:
                    redis_client.delete(f"ta_flake_uploads:{repo_id}")
                    process_flakes_for_repo(repo_id, commit_id)
        except LockError:
            log.warning("Unable to acquire process flakeslock for key %s.", lock_name)
            return {"successful": False}

        return {"successful": True}


def process_flakes_for_repo(repo_id: int, commit_id):
    # get all uploads pending process flakes in the entire repo? why stop at a given commit :D
    uploads_to_process = ReportSession.objects.filter(
        report__report_type=CommitReport.ReportType.TEST_RESULTS.value,
        report__commit__repository__repoid=repo_id,
        report__commit__commitid=commit_id,
        state__in=["v2_finished"],
    ).all()
    if not uploads_to_process:
        return

    if settings.BIGQUERY_WRITE_ENABLED:
        bq = BQDriver(repo_id)
        bq.write_flakes([upload for upload in uploads_to_process])

    pg = PGDriver(repo_id)
    pg.write_flakes([upload for upload in uploads_to_process])


TAProcessFlakesTaskRegistered = celery_app.register_task(TAProcessFlakesTask())
ta_process_flakes_task = celery_app.tasks[TAProcessFlakesTaskRegistered.name]
