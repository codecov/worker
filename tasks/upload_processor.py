import logging

from shared.celery_config import upload_processor_task_name
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.orm import Session as DbSession

from app import celery_app
from services.processing.processing import UploadArguments, process_upload
from services.report import ProcessingError
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

MAX_RETRIES = 5
FIRST_RETRY_DELAY = 20


def UPLOAD_PROCESSING_LOCK_NAME(repoid: int, commitid: str) -> str:
    """The upload_processing_lock.
    Only a single processing task may possess this lock at a time, because merging
    reports requires exclusive access to the report.

    This is used by the Upload, Notify and UploadCleanLabelsIndex tasks as well to
    verify if an upload for the commit is currently being processed.
    """
    return f"upload_processing_lock_{repoid}_{commitid}"


class UploadProcessorTask(BaseCodecovTask, name=upload_processor_task_name):
    """This is the second task of the series of tasks designed to process an `upload` made
    by the user

    To see more about the whole picture, see `tasks.upload.UploadTask`

    This task processes each user `upload`, and saves the results to db and minio storage

    The steps are:
        - Fetching the user uploaded report (from minio, or sometimes redis)
        - Running them through the language processors, and obtaining reports from that
        - Merging the generated reports to the already existing commit processed reports
        - Saving all that info to the database

    This task doesn't limit how many individual reports it receives for processing. It deals
        with as many as possible. But it is not expected that this task will receive a big
        number of `uploads` to be processed
    """

    acks_late = get_config("setup", "tasks", "upload", "acks_late", default=False)

    def run_impl(
        self,
        db_session: DbSession,
        *args,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        arguments: UploadArguments,
        intermediate_reports_in_redis=False,
        **kwargs,
    ):
        log.info(
            "Received upload processor task",
            extra={"arguments": arguments, "commit_yaml": commit_yaml},
        )

        def on_processing_error(error: ProcessingError):
            # the error is only retried on the first pass
            if error.is_retryable and self.request.retries == 0:
                log.info(
                    "Scheduling a retry due to retryable error",
                    extra={"error": error.as_dict()},
                )
                self.retry(max_retries=MAX_RETRIES, countdown=FIRST_RETRY_DELAY)

        return process_upload(
            on_processing_error,
            db_session,
            int(repoid),
            commitid,
            UserYaml(commit_yaml),
            arguments,
            intermediate_reports_in_redis,
        )


RegisteredUploadTask = celery_app.register_task(UploadProcessorTask())
upload_processor_task = celery_app.tasks[RegisteredUploadTask.name]
