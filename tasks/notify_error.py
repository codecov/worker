import logging
from dataclasses import dataclass

from asgiref.sync import async_to_sync
from shared.django_apps.core.models import Commit
from shared.django_apps.reports.models import CommitReport, ReportSession
from sqlalchemy.orm import Session

from celery_config import notify_error_task_name
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.notifier import BaseNotifier, NotifierResult
from services.yaml import UserYaml
from tasks.base import BaseCodecovTask, celery_app

log = logging.getLogger(__name__)


@dataclass
class ErrorNotifier(BaseNotifier):
    failed_upload: int
    total_upload: int

    def build_message(
        self,
    ) -> str:
        error_message = f"❗️ We couldn't process [{self.failed_upload}] out of [{self.total_upload}] uploads. Codecov cannot generate a coverage report with partially processed data. Please review the upload errors on the commit page."
        return error_message


class NotifyErrorTask(BaseCodecovTask, name=notify_error_task_name):
    def run_impl(
        self,
        _db_session: Session,
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
        #
        commit_yaml = UserYaml.from_dict(current_yaml)

        checkpoints = checkpoints_from_kwargs(UploadFlow, kwargs)

        commit = Commit.objects.get(repoid=repoid, commitid=commitid)
        assert commit

        report: CommitReport = commit.commitreport  # type:ignore

        uploads = ReportSession.objects.filter(report_id=report.id)

        num_total_upload = len(uploads)

        def is_failed(upload):
            if upload.state == "error":
                return True
            else:
                return False

        num_failed_upload = len(list(filter(is_failed, list(uploads))))

        log.info("Notifying upload errors", extra=dict())

        error_notifier = ErrorNotifier(
            commit, commit_yaml, num_failed_upload, num_total_upload
        )
        notification_result: NotifierResult = async_to_sync(error_notifier.notify())()
        match notification_result:
            case NotifierResult.COMMENT_POSTED:
                checkpoints.log(UploadFlow.NOTIFIED_ERROR)
            case NotifierResult.NO_PULL | NotifierResult.TORNGIT_ERROR:
                checkpoints.log(UploadFlow.ERROR_NOTIFYING_ERROR)

        log.info(
            "Finished notify error task",
            extra=dict(
                commit=commitid,
                repoid=repoid,
                commit_yaml=current_yaml,
                num_failed_upload=num_failed_upload,
                num_total_upload=num_total_upload,
                notification_result=notification_result.value,
            ),
        )


RegisteredNotifyErrorTask = celery_app.register_task(NotifyErrorTask())
notify_error_task = celery_app.tasks[RegisteredNotifyErrorTask.name]
