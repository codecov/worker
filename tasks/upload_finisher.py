import contextlib
import functools
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

from redis.exceptions import LockError
from redis.lock import Lock
from shared.celery_config import (
    compute_comparison_task_name,
    notify_task_name,
    pulls_task_name,
    timeseries_save_commit_measurements_task_name,
    upload_finisher_task_name,
)
from shared.metrics import Histogram
from shared.reports.editable import EditableReport, EditableReportFile
from shared.reports.enums import UploadState
from shared.reports.resources import Report
from shared.storage.exceptions import FileNotInStorageError
from shared.yaml import UserYaml

from app import celery_app
from celery_config import notify_error_task_name
from database.models import Commit, Pull
from database.models.core import Repository
from database.models.reports import Upload
from helpers.checkpoint_logger import _kwargs_key
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.metrics import KiB, MiB
from helpers.parallel import ParallelProcessing
from services.archive import ArchiveService, MinioEndpoints
from services.comparison import get_or_create_comparison
from services.redis import get_redis_connection
from services.report import ReportService, delete_uploads_by_sessionid
from services.report.raw_upload_processor import (
    SessionAdjustmentResult,
    clear_carryforward_sessions,
)
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask
from tasks.parallel_verification import parallel_verification_task
from tasks.upload_clean_labels_index import task_name as clean_labels_index_task_name
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME, UploadProcessorTask

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]")

PYREPORT_REPORT_JSON_SIZE = Histogram(
    "worker_tasks_upload_finisher_report_json_size",
    "Size (in bytes) of a report's report_json measured in `UploadFinisherTask`. Be aware: if we get more uploads for the same commit after `UploadFinisherTask` finishes, we will emit this metric again without deleting the first value. As a result, aggregate metrics will be biased towards smaller sizes.",
    buckets=[
        10 * KiB,
        100 * KiB,
        500 * KiB,
        1 * MiB,
        10 * MiB,
        100 * MiB,
        500 * MiB,
        1000 * MiB,
    ],
)

PYREPORT_CHUNKS_FILE_SIZE = Histogram(
    "worker_tasks_upload_finisher_chunks_file_size",
    "Size (in bytes) of a report's chunks file measured in `UploadFinisherTask`. Be aware: if we get more uploads for the same commit after `UploadFinisherTask` finishes, we will emit this metric again without deleting the first value. As a result, aggregate metrics will be biased towards smaller sizes.",
    buckets=[
        100 * KiB,
        500 * KiB,
        1 * MiB,
        10 * MiB,
        100 * MiB,
        500 * MiB,
        1000 * MiB,
        1500 * MiB,
    ],
)


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
        *,
        repoid,
        commitid,
        commit_yaml,
        report_code=None,
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

        parallel_processing = ParallelProcessing.from_task_args(repoid, **kwargs)

        if parallel_processing.is_parallel:
            # need to transform processing_results produced by chord to get it into the
            # same format as the processing_results produced from chain
            processing_results = {
                "processings_so_far": [
                    task["processings_so_far"][0] for task in processing_results
                ],
                "parallel_incremental_result": [
                    task["parallel_incremental_result"] for task in processing_results
                ],
            }

            report_lock = (
                acquire_report_lock(repoid, commitid, self.hard_time_limit_task)
                if parallel_processing is ParallelProcessing.PARALLEL
                else contextlib.nullcontext()
            )
            with report_lock:
                report_service = ReportService(commit_yaml)
                report = self.merge_incremental_reports(
                    commit_yaml,
                    repository,
                    commit,
                    report_service,
                    processing_results,
                    parallel_processing,
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

                if parallel_processing is ParallelProcessing.PARALLEL:
                    pr = processing_results["processings_so_far"][0]["arguments"].get(
                        "pr"
                    )
                    processor_task = UploadProcessorTask()
                    processor_task.save_report_results(
                        db_session,
                        report_service,
                        repository,
                        commit,
                        report,
                        pr,
                        report_code,
                    )

                else:
                    parallel_paths = report_service.save_parallel_report_to_archive(
                        commit, report, report_code
                    )
                    # now that we've built the report and stored it to GCS, we have what we need to
                    # compare the results with the current upload pipeline. We end execution of the
                    # finisher task here so that we don't cause any additional side-effects

                    # The verification task that will compare the results of the serial flow and
                    # the parallel flow, and log the result to determine if parallel flow is
                    # working properly.
                    parallel_verification_task.apply_async(
                        kwargs=dict(
                            repoid=repoid,
                            commitid=commitid,
                            commit_yaml=commit_yaml,
                            report_code=report_code,
                            parallel_paths=parallel_paths,
                            processing_results=processing_results,
                        ),
                    )

                    return

        lock_name = f"upload_finisher_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=5):
                commit_yaml = UserYaml(commit_yaml)
                commit.notified = False
                db_session.commit()
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

    def _emit_report_size_metrics(self, commit: Commit, report_code: str):
        # This is only used to emit chunks/report_json size metrics. We have to
        # do it here instead of in UploadProcessorTask where the report is
        # normally saved because that task saves after every upload and can't
        # tell when the report is final.
        try:
            if commit.report_json:
                report_json_size = len(json.dumps(commit.report_json))
                archive_service = ArchiveService(commit.repository)
                chunks_size = len(
                    archive_service.read_chunks(commit.commitid, report_code)
                )

                PYREPORT_REPORT_JSON_SIZE.observe(report_json_size)
                PYREPORT_CHUNKS_FILE_SIZE.observe(chunks_size)
        except Exception as e:
            log.exception(
                "Failed to emit report size metrics",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                ),
            )

    def finish_reports_processing(
        self,
        db_session,
        commit: Commit,
        commit_yaml: UserYaml,
        processing_results: dict,
        report_code,
        checkpoints,
    ):
        log.debug("In finish_reports_processing for commit: %s" % commit)
        commitid = commit.commitid
        repoid = commit.repoid

        self._emit_report_size_metrics(commit, report_code)

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
        self, commit_yaml: UserYaml, processing_results: dict
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

        actual_processing_results = processing_results.get("processings_so_far", [])
        return any(map(should_clean_for_processing_result, actual_processing_results))

    def should_call_notifications(
        self,
        commit: Commit,
        commit_yaml: UserYaml,
        processing_results: dict,
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

        processing_successses = [
            x["successful"] for x in processing_results.get("processings_so_far", [])
        ]

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

    def merge_incremental_reports(
        self,
        commit_yaml: dict,
        repository: Repository,
        commit: Commit,
        report_service: ReportService,
        processing_results: dict,
        parallel_processing: ParallelProcessing,
    ):
        archive_service = report_service.get_archive_service(repository)
        repoid = repository.repoid
        commitid = commit.id

        if parallel_processing is ParallelProcessing.PARALLEL:
            report = report_service.get_existing_report_for_commit(commit)
            if report is None:
                log.info(
                    "No base report found for parallel upload processing, using an empty report",
                    extra=dict(commit=commitid, repoid=repoid),
                )
                report = Report()

        else:
            fas_path = MinioEndpoints.parallel_upload_experiment.get_path(
                version="v4",
                repo_hash=archive_service.get_archive_hash(repository),
                commitid=commit.commitid,
                file_name="files_and_sessions",
            )
            chunks_path = MinioEndpoints.parallel_upload_experiment.get_path(
                version="v4",
                repo_hash=archive_service.get_archive_hash(repository),
                commitid=commit.commitid,
                file_name="chunks",
            )

            try:
                files_and_sessions = json.loads(archive_service.read_file(fas_path))
                chunks = archive_service.read_file(chunks_path).decode(errors="replace")
                report = report_service.build_report(
                    chunks,
                    files_and_sessions["files"],
                    files_and_sessions["sessions"],
                    None,
                )
            except (
                FileNotInStorageError
            ):  # there were no CFFs, so no report was stored in GCS
                log.info(
                    "No base report found for parallel upload processing, using an empty report",
                    extra=dict(commit=commitid, repoid=repoid),
                )
                report = Report()

        log.info(
            "Downloading %s incremental reports that were processed in parallel",
            len(processing_results["processings_so_far"]),
            extra=dict(
                repoid=repoid,
                commit=commitid,
                processing_results=processing_results["processings_so_far"],
                parent_task=self.request.parent_id,
            ),
        )

        def download_and_build_incremental_report(partial_report):
            chunks = archive_service.read_file(partial_report["chunks_path"]).decode(
                errors="replace"
            )
            files_and_sessions = json.loads(
                archive_service.read_file(partial_report["files_and_sessions_path"])
            )
            report = report_service.build_report(
                chunks,
                files_and_sessions["files"],
                files_and_sessions["sessions"],
                None,
                report_class=EditableReport,
            )
            return {
                "parallel_idx": partial_report["parallel_idx"],
                "report": report,
                "upload_pk": partial_report["upload_pk"],
            }

        def merge_report(cumulative_report: Report, obj):
            incremental_report: Report = obj["report"]

            if len(incremental_report.sessions) != 1:
                log.warning(
                    "Incremental report does not have expected session",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        upload_pk=obj["upload_pk"],
                        parallel_idx=obj["parallel_idx"],
                    ),
                )

            old_sessionid = next(iter(incremental_report.sessions))
            new_sessionid = cumulative_report.next_session_number()
            change_sessionid(incremental_report, old_sessionid, new_sessionid)

            session = incremental_report.sessions[new_sessionid]

            _session_id, session = cumulative_report.add_session(
                session, use_id_from_session=True
            )

            session_adjustment = SessionAdjustmentResult([], [])
            if flags := session.flags:
                session_adjustment = clear_carryforward_sessions(
                    cumulative_report, incremental_report, flags, UserYaml(commit_yaml)
                )

            cumulative_report.merge(incremental_report)

            if parallel_processing is ParallelProcessing.PARALLEL:
                # When we are fully parallel, we need to update the `Upload` in the database
                # with the final session_id (aka `order_number`) and other statuses
                db_session = commit.get_db_session()
                upload = (
                    db_session.query(Upload)
                    .filter(Upload.id_ == obj["upload_pk"])
                    .first()
                )
                upload.state_id = UploadState.PROCESSED.db_id
                upload.state = "processed"
                upload.order_number = new_sessionid
                delete_uploads_by_sessionid(
                    upload, session_adjustment.fully_deleted_sessions
                )
                db_session.flush()

            return cumulative_report

        with ThreadPoolExecutor(max_workers=10) as pool:  # max chosen arbitrarily
            unmerged_reports = pool.map(
                download_and_build_incremental_report,
                processing_results["parallel_incremental_result"],
            )

        log.info(
            "Merging %s incremental reports together",
            len(processing_results["processings_so_far"]),
            extra=dict(
                repoid=repoid,
                commit=commitid,
                processing_results=processing_results["processings_so_far"],
                parent_task=self.request.parent_id,
            ),
        )
        report = functools.reduce(merge_report, unmerged_reports, report)
        commit.get_db_session().flush()
        return report


RegisteredUploadTask = celery_app.register_task(UploadFinisherTask())
upload_finisher_task = celery_app.tasks[RegisteredUploadTask.name]


def acquire_report_lock(repoid: int, commitid: str, hard_time_limit: int) -> Lock:
    lock_name = UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid)
    redis_connection = get_redis_connection()
    return redis_connection.lock(
        lock_name,
        timeout=max(60 * 5, hard_time_limit),
        blocking_timeout=5,
    )


# TODO: maybe move this to `shared` if it turns out to be a better place for this
def change_sessionid(report: Report, old_id: int, new_id: int):
    """
    Modifies the `Report`, changing the session with `old_id` to have `new_id` instead.
    This patches up all the references to that session across all files and line records.

    In particular, it changes the id in all the `LineSession`s and `CoverageDatapoint`s,
    and does the equivalent of `calculate_present_sessions`.
    """
    session = report.sessions[new_id] = report.sessions.pop(old_id)
    session.id = new_id

    report_file: EditableReportFile
    for report_file in report._chunks:
        if report_file is None:
            continue

        all_sessions = set()

        for idx, _line in enumerate(report_file._lines):
            if not _line:
                continue

            # this turns the line into an actual `ReportLine`
            line = report_file._lines[idx] = report_file._line(_line)

            for session in line.sessions:
                if session.id == old_id:
                    session.id = new_id
                all_sessions.add(session.id)

            if line.datapoints:
                for point in line.datapoints:
                    if point.sessionid == old_id:
                        point.sessionid = new_id

        report_file._details["present_sessions"] = all_sessions
