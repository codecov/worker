import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from celery_config import notify_error_task_name
from database.enums import ReportType
from database.models import Commit, CommitReport, Upload
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.notifier import BaseNotifier, NotifierResult
from services.yaml import UserYaml
from tasks.base import BaseCodecovTask, celery_app

log = logging.getLogger(__name__)


@dataclass
class ErrorNotifier(BaseNotifier):
    failed_upload: int = 0
    total_upload: int = 0

    def build_message(
        self,
    ) -> str:
        error_message = f"❗️ We couldn't process [{self.failed_upload}] out of [{self.total_upload}] uploads. Codecov cannot generate a coverage report with partially processed data. Please review the upload errors on the commit page."
        return error_message


class NotifyErrorTask(BaseCodecovTask, name=notify_error_task_name):
    def run_impl(
        self,
        db_session: Session,
        *,
        repoid: int,
        commitid: str,
        current_yaml=None,
        **kwargs,
    ):
        log.info(
            "Starting notify error task",
            extra=dict(commit=commitid, repoid=repoid, commit_yaml=current_yaml),
        )

        # get all upload errors for this commit
        commit_yaml = UserYaml.from_dict(current_yaml)

        checkpoints = checkpoints_from_kwargs(
            UploadFlow,
            dict(**kwargs, context={"repoid": repoid}),
        )

        commits_query = db_session.query(Commit).filter(  # type:ignore
            Commit.repoid == repoid,
            Commit.commitid == commitid,  # type:ignore
        )

        commit: Commit = commits_query.first()
        assert commit, "Commit not found in database."

        report: CommitReport = commit.commit_report(ReportType.COVERAGE)  # type:ignore

        uploads = db_session.query(Upload).filter(Upload.report_id == report.id).all()

        num_total_upload = len(uploads)

        def is_failed(upload):
            if upload.state == "error":
                return True
            else:
                return False

        num_failed_upload = len(list(filter(is_failed, list(uploads))))

        log.info(
            "Notifying upload errors",
            extra=dict(
                repoid=repoid,
                commitid=commitid,
                num_failed_upload=num_failed_upload,
                num_total_upload=num_total_upload,
            ),
        )

        error_notifier = ErrorNotifier(
            commit,
            commit_yaml,
            failed_upload=num_failed_upload,
            total_upload=num_total_upload,
        )
        notification_result: NotifierResult = error_notifier.notify()
        match notification_result:
            case NotifierResult.COMMENT_POSTED:
                log.info(
                    "Finished notify error task",
                    extra=dict(
                        commit=commitid,
                        repoid=repoid,
                        commit_yaml=current_yaml,
                        num_failed_upload=num_failed_upload,
                        num_total_upload=num_total_upload,
                    ),
                )
                checkpoints.log(UploadFlow.NOTIFIED_ERROR)
                return {"success": True}
            case NotifierResult.NO_PULL | NotifierResult.TORNGIT_ERROR:
                checkpoints.log(UploadFlow.ERROR_NOTIFYING_ERROR)
                log.info(
                    "Failed to comment in notify error task",
                    extra=dict(
                        commit=commitid,
                        repoid=repoid,
                        commit_yaml=current_yaml,
                        num_failed_upload=num_failed_upload,
                        num_total_upload=num_total_upload,
                        notification_result=notification_result.value,
                    ),
                )
                return {"success": False}


RegisteredNotifyErrorTask = celery_app.register_task(NotifyErrorTask())
notify_error_task = celery_app.tasks[RegisteredNotifyErrorTask.name]
