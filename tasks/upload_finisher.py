import logging
import random
import re
from datetime import datetime
from enum import Enum

import sentry_sdk
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
from shared.yaml import UserYaml

from app import celery_app
from celery_config import notify_error_task_name
from database.models import Commit, Pull
from helpers.checkpoint_logger import _kwargs_key
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import UploadFlow
from services.archive import ArchiveService
from services.comparison import get_or_create_comparison
from services.processing.intermediate import (
    cleanup_intermediate_reports,
    load_intermediate_reports,
)
from services.processing.merging import merge_reports, update_uploads
from services.processing.metrics import LABELS_USAGE
from services.processing.state import ProcessingState, should_trigger_postprocessing
from services.processing.types import ProcessingResult
from services.redis import get_redis_connection
from services.report import ReportService
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask
from tasks.upload_clean_labels_index import task_name as clean_labels_index_task_name
from tasks.upload_processor import (
    MAX_RETRIES,
    UPLOAD_PROCESSING_LOCK_NAME,
    load_commit_diff,
    save_report_results,
)

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
        processing_results,
        *args,
        repoid,
        commitid,
        commit_yaml,
        report_code=None,
        intermediate_reports_in_redis=False,
        **kwargs,
    ):
        try:
            checkpoints = checkpoints_from_kwargs(UploadFlow, kwargs)
            checkpoints.log(UploadFlow.BATCH_PROCESSING_COMPLETE)
        except ValueError as e:
            log.warning("CheckpointLogger failed to log/submit", extra=dict(error=e))

        log.info(
            "Received upload_finisher task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                processing_results=processing_results,
                parent_task=self.request.parent_id,
            ),
        )
        repoid = int(repoid)
        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database."
        repository = commit.repository

        state = ProcessingState(repoid, commitid)

        processing_results = get_processing_results(processing_results)
        upload_ids = [upload["upload_id"] for upload in processing_results]
        pr = processing_results[0]["arguments"].get("pr")
        diff = load_commit_diff(commit, pr, self.name)

        try:
            with get_report_lock(repoid, commitid, self.hard_time_limit_task):
                report_service = ReportService(commit_yaml)
                archive_service = report_service.get_archive_service(repository)
                report = perform_report_merging(
                    report_service,
                    archive_service,
                    commit_yaml,
                    commit,
                    upload_ids,
                    intermediate_reports_in_redis,
                )

                log.info(
                    "Saving combined report",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        processing_results=processing_results,
                        parent_task=self.request.parent_id,
                    ),
                )

                save_report_results(
                    report_service, commit, report, diff, pr, report_code
                )
                state.mark_uploads_as_merged(upload_ids)

        except LockError:
            max_retry = 200 * 3**self.request.retries
            retry_in = min(random.randint(max_retry // 2, max_retry), 60 * 60 * 5)
            log.warning(
                "Unable to acquire report lock. Retrying",
                extra=dict(
                    commit=commitid,
                    repoid=repoid,
                    countdown=retry_in,
                    number_retries=self.request.retries,
                ),
            )
            self.retry(max_retries=MAX_RETRIES, countdown=retry_in)

        cleanup_intermediate_reports(
            archive_service, commit.commitid, upload_ids, intermediate_reports_in_redis
        )

        # Mark the repository as updated so it will appear earlier in the list
        # of recently-active repositories
        repository.updatestamp = datetime.now()

        if not should_trigger_postprocessing(state.get_upload_numbers()):
            return

        lock_name = f"upload_finisher_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=5):
                commit_yaml = UserYaml(commit_yaml)
                result = self.finish_reports_processing(
                    db_session,
                    commit,
                    commit_yaml,
                    processing_results,
                    report_code,
                    checkpoints,
                )
                self.app.tasks[
                    timeseries_save_commit_measurements_task_name
                ].apply_async(
                    kwargs=dict(commitid=commitid, repoid=repoid, dataset_names=None)
                )
                self.invalidate_caches(redis_connection, commit)
                log.info(
                    "Finished upload_finisher task",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        parent_task=self.request.parent_id,
                    ),
                )
                return result
        except LockError:
            log.warning(
                "Unable to acquire lock for key %s.",
                lock_name,
                extra=dict(
                    commit=commitid,
                    repoid=repoid,
                ),
            )

    def finish_reports_processing(
        self,
        db_session,
        commit: Commit,
        commit_yaml: UserYaml,
        processing_results: list[ProcessingResult],
        report_code,
        checkpoints,
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
                    task = self.app.tasks[notify_task_name].apply_async(
                        kwargs={
                            "repoid": repoid,
                            "commitid": commitid,
                            "current_yaml": commit_yaml.to_dict(),
                            _kwargs_key(UploadFlow): checkpoints.data,
                        },
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
                    task = self.app.tasks[notify_error_task_name].apply_async(
                        kwargs={
                            "repoid": repoid,
                            "commitid": commitid,
                            "current_yaml": commit_yaml.to_dict(),
                            _kwargs_key(UploadFlow): checkpoints.data,
                        },
                    )
        else:
            commit.state = "skipped"

        if self.should_clean_labels_index(commit_yaml, processing_results):
            # NOTE: according to tracing, the cleanup task is never actually run.
            # reasons for that might be that we indeed *never* have any flags
            # configured for `carryforward_mode=labels`, or the logic is somehow wrong?
            LABELS_USAGE.labels(codepath="cleanup_task").inc()
            task = self.app.tasks[clean_labels_index_task_name].apply_async(
                kwargs={
                    "repoid": repoid,
                    "commitid": commitid,
                    "report_code": report_code,
                },
            )
            log.info(
                "Scheduling clean_labels_index task",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    clean_labels_index_task_id=task.id,
                    parent_task=self.request.parent_id,
                ),
            )

        if checkpoints:
            checkpoints.log(UploadFlow.PROCESSING_COMPLETE)
            if not notifications_called:
                checkpoints.log(UploadFlow.SKIPPING_NOTIFICATION)

        return {"notifications_called": notifications_called}

    def should_clean_labels_index(
        self, commit_yaml: UserYaml, processing_results: list[ProcessingResult]
    ):
        """Returns True if any of the successful processings was uploaded using a flag
        that implies labels were uploaded with the report.
        """

        def should_clean_for_flag(flag: str):
            config = commit_yaml.get_flag_configuration(flag)
            return config and config.get("carryforward_mode", "") == "labels"

        def should_clean_for_processing_result(results):
            args = results.get("arguments", {})
            flags_str = args.get("flags", "")
            flags = flags_str.split(",") if flags_str else []
            return results["successful"] and any(map(should_clean_for_flag, flags))

        return any(map(should_clean_for_processing_result, processing_results))

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
    return redis_connection.lock(
        lock_name,
        timeout=max(60 * 5, hard_time_limit),
        blocking_timeout=5,
    )


@sentry_sdk.trace
def perform_report_merging(
    report_service: ReportService,
    archive_service: ArchiveService,
    commit_yaml: dict,
    commit: Commit,
    upload_ids: list[int],
    intermediate_reports_in_redis=False,
) -> Report:
    master_report = report_service.get_existing_report_for_commit(commit)
    if master_report is None:
        master_report = Report()

    intermediate_reports = load_intermediate_reports(
        archive_service, commit.commitid, upload_ids, intermediate_reports_in_redis
    )

    merge_result = merge_reports(
        UserYaml(commit_yaml), master_report, intermediate_reports
    )

    # Update the `Upload` in the database with the final session_id
    # (aka `order_number`) and other statuses
    update_uploads(commit.get_db_session(), merge_result)

    return master_report


def get_processing_results(processing_results: list) -> list[ProcessingResult]:
    results: list[ProcessingResult] = []
    for input_result in processing_results:
        if "processings_so_far" in input_result:
            result = input_result["processings_so_far"][0]
            if "upload_id" not in result:
                result["upload_id"] = input_result["parallel_incremental_result"][
                    "upload_pk"
                ]
            results.append(result)
        else:
            results.append(input_result)

    return results
