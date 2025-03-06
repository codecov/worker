import logging

from celery.exceptions import MaxRetriesExceededError
from redis.exceptions import LockError
from shared.celery_config import (
    compute_comparison_task_name,
    manual_upload_completion_trigger_task_name,
    notify_task_name,
    pulls_task_name,
)
from shared.reports.enums import UploadState

from app import celery_app
from database.enums import ReportType
from database.models import Commit, Pull
from database.models.reports import CommitReport, Upload
from services.comparison import get_or_create_comparison
from services.redis import get_redis_connection
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ManualTriggerTask(
    BaseCodecovTask, name=manual_upload_completion_trigger_task_name
):
    def run_impl(
        self,
        db_session,
        *,
        repoid: int,
        commitid: str,
        report_code: str,
        current_yaml=None,
        **kwargs,
    ):
        log.info(
            "Received manual trigger task",
            extra=dict(repoid=repoid, commit=commitid, report_code=report_code),
        )
        repoid = int(repoid)
        lock_name = f"manual_trigger_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(
                lock_name,
                timeout=60 * 5,
                blocking_timeout=5,
            ):
                return self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=current_yaml,
                    report_code=report_code,
                    **kwargs,
                )
        except LockError:
            log.warning(
                "Unable to acquire lock",
                extra=dict(
                    commit=commitid,
                    repoid=repoid,
                    number_retries=self.request.retries,
                    lock_name=lock_name,
                ),
            )
            return {"notifications_called": False, "message": "Unable to acquire lock"}

    def process_impl_within_lock(
        self,
        *,
        db_session,
        repoid,
        commitid,
        commit_yaml,
        report_code,
        **kwargs,
    ):
        commit = (
            db_session.query(Commit)
            .filter(
                Commit.repoid == repoid,
                Commit.commitid == commitid,
            )
            .first()
        )
        uploads = (
            db_session.query(Upload)
            .join(CommitReport)
            .filter(
                CommitReport.code == report_code,
                CommitReport.commit == commit,
                (CommitReport.report_type == None)  # noqa: E711
                | (CommitReport.report_type == ReportType.COVERAGE.value),
            )
        )
        still_processing = 0
        for upload in uploads:
            if not upload.state or upload.state_id == UploadState.UPLOADED.db_id:
                still_processing += 1
        if still_processing == 0:
            self.trigger_notifications(repoid, commitid, commit_yaml)
            if commit.pullid:
                self.trigger_pull_sync(db_session, repoid, commit)
            return {
                "notifications_called": True,
                "message": "All uploads are processed. Triggering notifications.",
            }
        else:
            # reschedule the task
            try:
                log.info(
                    "Retrying ManualTriggerTask. Some uploads are still being processed."
                )
                retry_in = 60 * 3**self.request.retries
                self.retry(max_retries=5, countdown=retry_in)
            except MaxRetriesExceededError:
                log.warning(
                    "Not attempting to wait for all uploads to get processed since we already retried too many times",
                    extra=dict(
                        repoid=commit.repoid,
                        commit=commit.commitid,
                        max_retries=5,
                        next_countdown_would_be=retry_in,
                    ),
                )
                return {
                    "notifications_called": False,
                    "message": "Uploads are still in process and the task got retired so many times. Not triggering notifications.",
                }

    def trigger_notifications(self, repoid, commitid, commit_yaml):
        log.info(
            "Scheduling notify task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml.to_dict() if commit_yaml else None,
            ),
        )
        self.app.tasks[notify_task_name].apply_async(
            kwargs=dict(
                repoid=repoid,
                commitid=commitid,
                current_yaml=commit_yaml.to_dict() if commit_yaml else None,
            )
        )

    def trigger_pull_sync(self, db_session, repoid, commit):
        pull = (
            db_session.query(Pull)
            .filter_by(repoid=commit.repoid, pullid=commit.pullid)
            .first()
        )

        if pull:
            head = pull.get_head_commit()
            if head is None or head.timestamp <= commit.timestamp:
                pull.head = commit.commitid
            if pull.head == commit.commitid:
                db_session.commit()
                log.info(
                    "Scheduling pulls syc task",
                    extra=dict(
                        repoid=repoid,
                        pullid=pull.pullid,
                    ),
                )
                self.app.tasks[pulls_task_name].apply_async(
                    kwargs=dict(
                        repoid=repoid,
                        pullid=pull.pullid,
                        should_send_notifications=False,
                    )
                )
                compared_to = pull.get_comparedto_commit()
                if compared_to:
                    comparison = get_or_create_comparison(
                        db_session, compared_to, commit
                    )
                    db_session.commit()
                    self.app.tasks[compute_comparison_task_name].apply_async(
                        kwargs=dict(comparison_id=comparison.id)
                    )


RegisteredManualTriggerTask = celery_app.register_task(ManualTriggerTask())
manual_trigger_task = celery_app.tasks[RegisteredManualTriggerTask.name]
