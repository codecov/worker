import logging

import sentry_sdk
from asgiref.sync import async_to_sync
from shared.celery_config import upload_processor_task_name
from shared.config import get_config
from shared.torngit.exceptions import TorngitError
from shared.yaml import UserYaml
from sqlalchemy.orm import Session as DbSession

from app import celery_app
from database.enums import CommitErrorTypes
from database.models import Commit
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME, Pull
from helpers.cache import cache
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.save_commit_error import save_commit_error
from services.processing.processing import UploadArguments, process_upload
from services.report import ProcessingError, Report, ReportService
from services.repository import get_repo_provider_service
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
        )


RegisteredUploadTask = celery_app.register_task(UploadProcessorTask())
upload_processor_task = celery_app.tasks[RegisteredUploadTask.name]


@sentry_sdk.trace
@cache.cache_function(ttl=60 * 60)  # the commit diff is immutable
def load_commit_diff(
    commit: Commit, pr: Pull | None, task_name: str | None
) -> dict | None:
    repository = commit.repository
    commitid = commit.commitid
    try:
        installation_name_to_use = (
            get_installation_name_for_owner_for_task(task_name, repository.owner)
            if task_name
            else GITHUB_APP_INSTALLATION_DEFAULT_NAME
        )
        repository_service = get_repo_provider_service(
            repository, installation_name_to_use=installation_name_to_use
        )
        return async_to_sync(repository_service.get_commit_diff)(commitid)

    # TODO: can we maybe get rid of all this logging?
    except TorngitError:
        # When this happens, we have that commit.totals["diff"] is not available.
        # Since there is no way to calculate such diff without the git commit,
        # then we assume having the rest of the report saved there is better than the
        # alternative of refusing an otherwise "good" report because of the lack of diff
        log.warning(
            "Could not apply diff to report because there was an error fetching diff from provider",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
            ),
            exc_info=True,
        )
    except RepositoryWithoutValidBotError:
        save_commit_error(
            commit,
            error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
            error_params=dict(
                repoid=commit.repoid,
                pr=pr,
            ),
        )

        log.warning(
            "Could not apply diff to report because there is no valid bot found for that repo",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
            ),
            exc_info=True,
        )

    return None


@sentry_sdk.trace
def save_report_results(
    report_service: ReportService,
    commit: Commit,
    report: Report,
    diff: dict | None,
    # TODO: maybe remove this parameter, as its only used to update `commit`:
    pr: Pull | None,
    report_code=None,
):
    """Saves the result of `report` to the commit database and chunks archive

    This method only takes care of getting a processed Report to the database and archive.

    It also tries to calculate the diff of the report (which uses commit info
        from th git provider), but it it fails to do so, it just moves on without such diff
    """
    log.debug("In save_report_results for commit: %s" % commit)

    if diff:
        report.apply_diff(diff)

    if pr is not None:
        try:
            commit.pullid = int(pr)
        except (ValueError, TypeError):
            log.warning(
                "Cannot set PR value on commit",
                extra=dict(repoid=commit.repoid, commit=commit.commitid, pr_value=pr),
            )

    res = report_service.save_report(commit, report, report_code)
    commit.get_db_session().commit()
    return res
