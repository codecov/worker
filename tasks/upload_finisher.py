import logging
import random
import re
from datetime import datetime, timedelta, timezone
from enum import Enum

import sentry_sdk
from asgiref.sync import async_to_sync
from redis.exceptions import LockError
from redis.lock import Lock
from shared.celery_config import (
    compute_comparison_task_name,
    notify_task_name,
    pulls_task_name,
    timeseries_save_commit_measurements_task_name,
    upload_finisher_task_name,
)
from shared.reports.resources import Report
from shared.timeseries.helpers import is_timeseries_enabled
from shared.torngit.exceptions import TorngitError
from shared.yaml import UserYaml

from app import celery_app
from celery_config import notify_error_task_name
from database.enums import CommitErrorTypes
from database.models import Commit, Pull
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from helpers.cache import cache
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.save_commit_error import save_commit_error
from services.comparison import get_or_create_comparison
from services.processing.intermediate import (
    cleanup_intermediate_reports,
    load_intermediate_reports,
)
from services.processing.merging import merge_reports, update_uploads
from services.processing.state import ProcessingState, should_trigger_postprocessing
from services.processing.types import ProcessingResult
from services.redis import get_redis_connection
from services.report import ReportService
from services.repository import get_repo_provider_service
from services.timeseries import repository_datasets_query
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask
from tasks.upload_processor import MAX_RETRIES, UPLOAD_PROCESSING_LOCK_NAME

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]")


class ShouldCallNotifyResult(Enum):
    DO_NOT_NOTIFY = "do_not_notify"
    NOTIFY_ERROR = "notify_error"
    NOTIFY = "notify"


class UploadFinisherTask(BaseCodecovTask, name=upload_finisher_task_name):
    """This is the third task of the series of tasks designed to process an `upload` made
    by the user

    To see more about the whole picture, see `tasks.upload.UploadTask`

    This task does the finishing steps after a group of uploads is processed

    The steps are:
        - Schedule the set_pending task, depending on the case
        - Schedule notification tasks, depending on the case
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

        if not should_trigger_postprocessing(state.get_upload_numbers()):
            UploadFlow.log(UploadFlow.PROCESSING_COMPLETE)
            UploadFlow.log(UploadFlow.SKIPPING_NOTIFICATION)
            return

        lock_name = f"upload_finisher_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=5):
                result = self.finish_reports_processing(
                    db_session,
                    commit,
                    commit_yaml,
                    processing_results,
                    report_code,
                )
                if is_timeseries_enabled():
                    dataset_names = [
                        dataset.name
                        for dataset in repository_datasets_query(repository)
                    ]
                    if dataset_names:
                        self.app.tasks[
                            timeseries_save_commit_measurements_task_name
                        ].apply_async(
                            kwargs=dict(
                                commitid=commitid,
                                repoid=repoid,
                                dataset_names=dataset_names,
                            )
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
                return result
        except LockError:
            log.warning("Unable to acquire lock", extra=dict(lock_name=lock_name))
            UploadFlow.log(UploadFlow.FINISHER_LOCK_ERROR)

    def finish_reports_processing(
        self,
        db_session,
        commit: Commit,
        commit_yaml: UserYaml,
        processing_results: list[ProcessingResult],
        report_code,
    ):
        log.debug("In finish_reports_processing for commit: %s" % commit)
        commitid = commit.commitid
        repoid = commit.repoid

        # always notify, let the notify handle if it should submit
        notifications_called = False
        if not regexp_ci_skip.search(commit.message or ""):
            match self.should_call_notifications(
                commit, commit_yaml, processing_results, report_code
            ):
                case ShouldCallNotifyResult.NOTIFY:
                    notifications_called = True
                    notify_kwargs = {
                        "repoid": repoid,
                        "commitid": commitid,
                        "current_yaml": commit_yaml.to_dict(),
                    }
                    notify_kwargs = UploadFlow.save_to_kwargs(notify_kwargs)
                    task = self.app.tasks[notify_task_name].apply_async(
                        kwargs=notify_kwargs
                    )
                    log.info(
                        "Scheduling notify task",
                        extra=dict(
                            repoid=repoid,
                            commit=commitid,
                            commit_yaml=commit_yaml.to_dict(),
                            processing_results=processing_results,
                            notify_task_id=task.id,
                            parent_task=self.request.parent_id,
                        ),
                    )
                    if commit.pullid:
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
                                    self.app.tasks[
                                        compute_comparison_task_name
                                    ].apply_async(
                                        kwargs=dict(comparison_id=comparison.id)
                                    )
                case ShouldCallNotifyResult.DO_NOT_NOTIFY:
                    notifications_called = False
                    log.info(
                        "Skipping notify task",
                        extra=dict(
                            repoid=repoid,
                            commit=commitid,
                            commit_yaml=commit_yaml.to_dict(),
                            processing_results=processing_results,
                            parent_task=self.request.parent_id,
                        ),
                    )
                case ShouldCallNotifyResult.NOTIFY_ERROR:
                    notifications_called = False
                    notify_error_kwargs = {
                        "repoid": repoid,
                        "commitid": commitid,
                        "current_yaml": commit_yaml.to_dict(),
                    }
                    notify_error_kwargs = UploadFlow.save_to_kwargs(notify_error_kwargs)
                    task = self.app.tasks[notify_error_task_name].apply_async(
                        kwargs=notify_error_kwargs
                    )
        else:
            commit.state = "skipped"

        UploadFlow.log(UploadFlow.PROCESSING_COMPLETE)
        if not notifications_called:
            UploadFlow.log(UploadFlow.SKIPPING_NOTIFICATION)

        return {"notifications_called": notifications_called}

    def should_call_notifications(
        self,
        commit: Commit,
        commit_yaml: UserYaml,
        processing_results: list[ProcessingResult],
        report_code,
    ) -> ShouldCallNotifyResult:
        extra_dict = {
            "repoid": commit.repoid,
            "commitid": commit.commitid,
            "commit_yaml": commit_yaml,
            "processing_results": processing_results,
            "report_code": report_code,
            "parent_task": self.request.parent_id,
        }

        manual_trigger = read_yaml_field(
            commit_yaml, ("codecov", "notify", "manual_trigger")
        )
        if manual_trigger:
            log.info(
                "Not scheduling notify because manual trigger is used",
                extra=extra_dict,
            )
            return ShouldCallNotifyResult.DO_NOT_NOTIFY
        # Notifications should be off in case of local uploads, and report code wouldn't be null in that case
        if report_code is not None:
            log.info(
                "Not scheduling notify because it's a local upload",
                extra=extra_dict,
            )
            return ShouldCallNotifyResult.DO_NOT_NOTIFY

        after_n_builds = (
            read_yaml_field(commit_yaml, ("codecov", "notify", "after_n_builds")) or 0
        )
        if after_n_builds > 0:
            report = ReportService(commit_yaml).get_existing_report_for_commit(commit)
            number_sessions = len(report.sessions) if report is not None else 0
            if after_n_builds > number_sessions:
                log.info(
                    "Not scheduling notify because `after_n_builds` is %s and we only found %s builds",
                    after_n_builds,
                    number_sessions,
                    extra=extra_dict,
                )
                return ShouldCallNotifyResult.DO_NOT_NOTIFY

        processing_successses = [x["successful"] for x in processing_results]

        if read_yaml_field(
            commit_yaml,
            ("codecov", "notify", "notify_error"),
            _else=False,
        ):
            if len(processing_successses) == 0 or not all(processing_successses):
                log.info(
                    "Not scheduling notify because there is a non-successful processing result",
                    extra=extra_dict,
                )

                return ShouldCallNotifyResult.NOTIFY_ERROR
        else:
            if not any(processing_successses):
                return ShouldCallNotifyResult.DO_NOT_NOTIFY

        return ShouldCallNotifyResult.NOTIFY

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


RegisteredUploadTask = celery_app.register_task(UploadFinisherTask())
upload_finisher_task = celery_app.tasks[RegisteredUploadTask.name]


def get_report_lock(repoid: int, commitid: str, hard_time_limit: int) -> Lock:
    lock_name = UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid)
    redis_connection = get_redis_connection()

    timeout = 60 * 5
    if hard_time_limit:
        timeout = max(timeout, hard_time_limit)

    return redis_connection.lock(
        lock_name,
        timeout=timeout,
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
