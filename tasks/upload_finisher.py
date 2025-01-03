import logging
import random
from datetime import datetime, timedelta, timezone

import sentry_sdk
from asgiref.sync import async_to_sync
from redis.exceptions import LockError
from redis.lock import Lock
from shared.celery_config import (
    notification_orchestrator_task_name,
    timeseries_save_commit_measurements_task_name,
    upload_finisher_task_name,
)
from shared.reports.resources import Report
from shared.torngit.exceptions import TorngitError
from shared.yaml import UserYaml

from app import celery_app
from database.enums import CommitErrorTypes
from database.models import Commit
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from helpers.cache import cache
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.save_commit_error import save_commit_error
from services.processing.intermediate import (
    cleanup_intermediate_reports,
    load_intermediate_reports,
)
from services.processing.merging import merge_reports, update_uploads
from services.processing.state import ProcessingState
from services.processing.types import ProcessingResult
from services.redis import get_redis_connection
from services.report import ReportService
from services.repository import get_repo_provider_service
from tasks.base import BaseCodecovTask
from tasks.upload_processor import MAX_RETRIES, UPLOAD_PROCESSING_LOCK_NAME

log = logging.getLogger(__name__)


class UploadFinisherTask(BaseCodecovTask, name=upload_finisher_task_name):
    """This is the third task of the series of tasks designed to process an `upload` made
    by the user

    To see more about the whole picture, see `tasks.upload.UploadTask`

    This task does the finishing steps after a group of uploads is processed

    The steps are:
        - Merging reports into one report for GCP and update Upload records with status
        - Schedule notification orchestrator task
        - Invalidating whatever cache is done
    """

    def run_impl(
        self,
        db_session,
        processing_results: list[ProcessingResult],
        *args,
        repoid: int,
        commitid: str,
        commit_yaml,
        report_code: str | None = None,
        **kwargs,
    ):
        try:
            UploadFlow.log(UploadFlow.BATCH_PROCESSING_COMPLETE)
        except ValueError as e:
            log.warning("CheckpointLogger failed to log/submit", extra=dict(error=e))

        log.info(
            "Received upload_finisher task",
            extra={"processing_results": processing_results},
        )

        repoid = int(repoid)
        commit_yaml = UserYaml(commit_yaml)

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database."
        repository = commit.repository

        state = ProcessingState(repoid, commitid)

        upload_ids = [upload["upload_id"] for upload in processing_results]
        diff = load_commit_diff(commit, self.name)

        try:
            with get_report_lock(repoid, commitid, self.hard_time_limit_task):
                report_service = ReportService(commit_yaml)
                report = perform_report_merging(
                    report_service, commit_yaml, commit, processing_results
                )

                log.info(
                    "Saving combined report",
                    extra={"processing_results": processing_results},
                )

                if diff:
                    report.apply_diff(diff)
                report_service.save_report(commit, report, report_code)

                db_session.commit()
                state.mark_uploads_as_merged(upload_ids)
        except LockError:
            max_retry = 200 * 3**self.request.retries
            retry_in = min(random.randint(max_retry // 2, max_retry), 60 * 60 * 5)
            log.warning(
                "Unable to acquire report lock. Retrying",
                extra=dict(countdown=retry_in, number_retries=self.request.retries),
            )
            self.retry(max_retries=MAX_RETRIES, countdown=retry_in)

        cleanup_intermediate_reports(upload_ids)

        # Call the notification orchestrator task
        lock_name = f"upload_finisher_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=5):
                notification_orchestrator_kwargs = {
                    "repoid": repoid,
                    "commitid": commitid,
                    "commit_yaml": commit_yaml.to_dict(),
                    "processing_results": processing_results,
                    "report_code": report_code,
                }
                notification_orchestrator_kwargs = UploadFlow.save_to_kwargs(
                    notification_orchestrator_kwargs
                )
                # TODO: add log to add the notification orchestrator task
                self.app.tasks[notification_orchestrator_task_name].apply_async(
                    kwargs=notification_orchestrator_kwargs
                )
                self.app.tasks[
                    timeseries_save_commit_measurements_task_name
                ].apply_async(
                    kwargs=dict(commitid=commitid, repoid=repoid, dataset_names=None)
                )
                # Mark the repository as updated so it will appear earlier in the list
                # of recently-active repositories
                now = datetime.now(tz=timezone.utc)
                threshold = now - timedelta(minutes=30)
                if not repository.updatestamp or repository.updatestamp < threshold:
                    repository.updatestamp = now
                    db_session.commit()

                self.invalidate_caches(redis_connection, commit)

                log.info("Finished upload_finisher task")
                UploadFlow.log(UploadFlow.PROCESSING_COMPLETE)
                return {"result": "finisher done"}
        except LockError:
            log.warning("Unable to acquire lock", extra=dict(lock_name=lock_name))
            UploadFlow.log(UploadFlow.FINISHER_LOCK_ERROR)

    def invalidate_caches(self, redis_connection, commit: Commit):
        redis_connection.delete("cache/{}/tree/{}".format(commit.repoid, commit.branch))
        redis_connection.delete(
            "cache/{0}/tree/{1}".format(commit.repoid, commit.commitid)
        )
        repository = commit.repository
        key = ":".join((repository.service, repository.owner.username, repository.name))
        if commit.branch:
            redis_connection.hdel("badge", ("%s:%s" % (key, (commit.branch))).lower())
            if commit.branch == repository.branch:
                redis_connection.hdel("badge", ("%s:" % key).lower())


def get_report_lock(repoid: int, commitid: str, hard_time_limit: int) -> Lock:
    lock_name = UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid)
    redis_connection = get_redis_connection()
    return redis_connection.lock(
        lock_name,
        timeout=max(60 * 5, hard_time_limit),
        blocking_timeout=5,
    )


@sentry_sdk.trace
def perform_report_merging(
    report_service: ReportService,
    commit_yaml: UserYaml,
    commit: Commit,
    processing_results: list[ProcessingResult],
) -> Report:
    master_report = report_service.get_existing_report_for_commit(commit)
    if master_report is None:
        master_report = Report()

    upload_ids = [
        upload["upload_id"] for upload in processing_results if upload["successful"]
    ]
    intermediate_reports = load_intermediate_reports(upload_ids)

    master_report, merge_result = merge_reports(
        commit_yaml, master_report, intermediate_reports
    )

    # Update the `Upload` in the database with the final session_id
    # (aka `order_number`) and other statuses
    update_uploads(
        commit.get_db_session(),
        commit_yaml,
        processing_results,
        intermediate_reports,
        merge_result,
    )

    return master_report


@sentry_sdk.trace
@cache.cache_function(ttl=60 * 60)  # the commit diff is immutable
def load_commit_diff(commit: Commit, task_name: str | None = None) -> dict | None:
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

    # TODO(swatinem): can we maybe get rid of all this logging?
    except TorngitError:
        # When this happens, we have that commit.totals["diff"] is not available.
        # Since there is no way to calculate such diff without the git commit,
        # then we assume having the rest of the report saved there is better than the
        # alternative of refusing an otherwise "good" report because of the lack of diff
        log.warning(
            "Could not apply diff to report because there was an error fetching diff from provider",
            exc_info=True,
        )
    except RepositoryWithoutValidBotError:
        save_commit_error(
            commit,
            error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
        )
        log.warning(
            "Could not apply diff to report because there is no valid bot found for that repo",
            exc_info=True,
        )

    return None


RegisteredUploadTask = celery_app.register_task(UploadFinisherTask())
upload_finisher_task = celery_app.tasks[RegisteredUploadTask.name]
