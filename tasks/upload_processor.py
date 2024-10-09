import logging
import random
from typing import Any

import sentry_sdk
from asgiref.sync import async_to_sync
from celery.exceptions import CeleryError, SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.celery_config import upload_processor_task_name
from shared.config import get_config
from shared.torngit.exceptions import TorngitError
from shared.yaml import UserYaml
from sqlalchemy.exc import SQLAlchemyError

from app import celery_app
from database.enums import CommitErrorTypes
from database.models import Commit, Upload
from database.models.core import Pull, Repository
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.parallel import ParallelProcessing
from helpers.parallel_upload_processing import (
    save_final_serial_report_results,
    save_incremental_report_results,
)
from helpers.reports import delete_archive_setting
from helpers.save_commit_error import save_commit_error
from services.redis import get_redis_connection
from services.report import ProcessingResult, RawReportInfo, Report, ReportService
from services.report.parser.types import VersionOneParsedRawReport
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
        db_session,
        previous_results,
        *,
        repoid,
        commitid,
        commit_yaml,
        arguments_list,
        report_code=None,
        **kwargs,
    ):
        repoid = int(repoid)
        log.info(
            "Received upload processor task",
            extra=dict(
                repoid=repoid, commit=commitid, in_parallel=kwargs.get("in_parallel")
            ),
        )

        parallel_processing = ParallelProcessing.from_task_args(**kwargs)

        if parallel_processing.is_parallel:
            log.info(
                "Using parallel upload processing, skip acquiring upload processing lock",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    report_code=report_code,
                    parent_task=self.request.parent_id,
                ),
            )

            return self.process_upload(
                db_session=db_session,
                previous_results={},
                repoid=repoid,
                commitid=commitid,
                commit_yaml=commit_yaml,
                arguments_list=arguments_list,
                report_code=report_code,
                parallel_processing=parallel_processing,
            )

        lock_name = UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid)
        redis_connection = get_redis_connection()
        try:
            log.info(
                "Acquiring upload processing lock",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    report_code=report_code,
                    lock_name=lock_name,
                    parent_task=self.request.parent_id,
                ),
            )
            with redis_connection.lock(
                lock_name,
                timeout=max(60 * 5, self.hard_time_limit_task),
                blocking_timeout=5,
            ):
                log.info(
                    "Obtained upload processing lock, starting",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        parent_task=self.request.parent_id,
                        report_code=report_code,
                    ),
                )

                return self.process_upload(
                    db_session=db_session,
                    previous_results=previous_results,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    arguments_list=arguments_list,
                    report_code=report_code,
                    parallel_processing=parallel_processing,
                )
        except LockError:
            max_retry = 200 * 3**self.request.retries
            retry_in = min(random.randint(max_retry // 2, max_retry), 60 * 60 * 5)
            log.warning(
                "Unable to acquire lock for key %s. Retrying",
                lock_name,
                extra=dict(
                    commit=commitid,
                    repoid=repoid,
                    countdown=retry_in,
                    number_retries=self.request.retries,
                ),
            )
            self.retry(max_retries=MAX_RETRIES, countdown=retry_in)

    @sentry_sdk.trace
    def process_upload(
        self,
        db_session,
        previous_results: dict,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        arguments_list: list[dict],
        report_code,
        parallel_processing: ParallelProcessing,
    ):
        processings_so_far: list[dict] = previous_results.get("processings_so_far", [])
        n_processed = 0
        n_failed = 0

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database."
        repository = commit.repository
        pr = None
        report_service = ReportService(UserYaml(commit_yaml))

        in_parallel = parallel_processing.is_parallel
        parallel_processing.emit_metrics("upload_processor")

        if in_parallel:
            log.info(
                "Creating empty report to store incremental result",
                extra=dict(commit=commitid, repo=repoid),
            )
            report = Report()
        else:
            report = report_service.get_existing_report_for_commit(
                commit, report_code=report_code
            )
            if report is None:
                log.info(
                    "No existing report for commit",
                    extra=dict(commit=commit.commitid),
                )
                report = Report()

        raw_reports: list[RawReportInfo] = []
        try:
            for arguments in arguments_list:
                pr = arguments.get("pr")
                upload_obj = (
                    db_session.query(Upload)
                    .filter_by(id_=arguments.get("upload_pk"))
                    .first()
                )
                log.info(
                    f"Processing individual report {arguments.get('reportid')}"
                    + (" (in parallel)" if in_parallel else ""),
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        arguments=arguments,
                        commit_yaml=commit_yaml,
                        upload=upload_obj.id_,
                        parent_task=self.request.parent_id,
                        in_parallel=in_parallel,
                    ),
                )
                individual_info: dict[str, Any] = {"arguments": arguments}
                try:
                    raw_report_info = RawReportInfo()
                    processing_result = self.process_individual_report(
                        report_service,
                        commit,
                        report,
                        upload_obj,
                        raw_report_info,
                        parallel_processing,
                    )
                    # NOTE: this is only used because test mocking messes with the return value here.
                    # in normal flow, the function mutates the argument instead.
                    if processing_result.report:
                        report = processing_result.report
                except (CeleryError, SoftTimeLimitExceeded, SQLAlchemyError):
                    raise

                if error := processing_result.error:
                    n_failed += 1
                    individual_info["successful"] = False
                    individual_info["error"] = error.as_dict()

                else:
                    n_processed += 1
                    individual_info["successful"] = True
                processings_so_far.append(individual_info)

                if raw_report_info.raw_report:
                    raw_reports.append(raw_report_info)

            log.info(
                f"Finishing the processing of {n_processed} reports"
                + (" (in parallel)" if in_parallel else ""),
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    parent_task=self.request.parent_id,
                    in_parallel=in_parallel,
                ),
            )

            parallel_incremental_result = None
            results_dict = {}
            if in_parallel:
                upload_id = arguments_list[0].get("upload_pk")
                parallel_incremental_result = save_incremental_report_results(
                    report_service,
                    commit,
                    report,
                    upload_id,
                    report_code,
                )

                log.info(
                    "Saved incremental report results to storage",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        incremental_result_path=parallel_incremental_result,
                    ),
                )
            else:
                results_dict = self.save_report_results(
                    db_session,
                    report_service,
                    repository,
                    commit,
                    report,
                    pr,
                    report_code,
                )

                # Save the final accumulated result from the serial flow for the
                # ParallelVerification task to compare with later, for the parallel
                # experiment. The report being saved is not necessarily the final
                # report for the commit, as more uploads can still be made.
                if parallel_processing is ParallelProcessing.EXPERIMENT_SERIAL:
                    final_serial_report_url = save_final_serial_report_results(
                        report_service, commit, report, report_code, arguments_list
                    )
                    log.info(
                        "Saved final serial report results to storage",
                        extra=dict(
                            repoid=repoid,
                            commit=commitid,
                            final_serial_result_path=final_serial_report_url,
                        ),
                    )

            if raw_reports:
                self.postprocess_raw_reports(report_service, commit, raw_reports)

            log.info(
                f"Processed {n_processed} reports (+ {n_failed} failed)"
                + (" (in parallel)" if in_parallel else ""),
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    commit_yaml=commit_yaml,
                    url=results_dict.get("url"),
                    parent_task=self.request.parent_id,
                    in_parallel=in_parallel,
                ),
            )

            processing_results: dict = {
                "processings_so_far": processings_so_far,
            }
            if in_parallel:
                processing_results["parallel_incremental_result"] = (
                    parallel_incremental_result
                )

            return processing_results
        except CeleryError:
            raise
        except Exception:
            commit.state = "error"
            log.exception(
                "Could not properly process commit",
                extra=dict(repoid=repoid, commit=commitid),
            )
            raise

    @sentry_sdk.trace
    def process_individual_report(
        self,
        report_service: ReportService,
        commit: Commit,
        report: Report,
        upload: Upload,
        raw_report_info: RawReportInfo,
        parallel_processing: ParallelProcessing,
    ) -> ProcessingResult:
        processing_result = report_service.build_report_from_raw_content(
            report, raw_report_info, upload
        )
        if (
            processing_result.error is not None
            and processing_result.error.is_retryable
            and self.request.retries == 0  # the error is only retried on the first pass
        ):
            log.info(
                f"Scheduling a retry in {FIRST_RETRY_DELAY} due to retryable error",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    upload_id=upload.id,
                    processing_result_error_code=processing_result.error.code,
                    processing_result_error_params=processing_result.error.params,
                    parent_task=self.request.parent_id,
                ),
            )
            self.retry(max_retries=MAX_RETRIES, countdown=FIRST_RETRY_DELAY)

        # for the parallel experiment, we don't want to modify anything in the
        # database, so we disable it here
        if parallel_processing is not ParallelProcessing.EXPERIMENT_PARALLEL:
            report_service.update_upload_with_processing_result(
                upload, processing_result
            )

        return processing_result

    @sentry_sdk.trace
    def postprocess_raw_reports(
        self,
        report_service: ReportService,
        commit: Commit,
        reports: list[RawReportInfo],
    ):
        should_delete_archive_setting = delete_archive_setting(
            report_service.current_yaml
        )
        archive_service = report_service.get_archive_service(commit.repository)

        for report_info in reports:
            archive_url = report_info.archive_url

            if should_delete_archive_setting and not report_info.error:
                if not archive_url.startswith("http"):
                    archive_service.delete_file(archive_url)

            elif isinstance(report_info.raw_report, VersionOneParsedRawReport):
                # only a version 1 report needs to be "rewritten readable"

                archive_service.write_file(
                    archive_url, report_info.raw_report.content().getvalue()
                )

    @sentry_sdk.trace
    def save_report_results(
        self,
        db_session,
        report_service: ReportService,
        repository: Repository,
        commit: Commit,
        report: Report,
        pr: Pull,
        report_code=None,
    ):
        """Saves the result of `report` to the commit database and chunks archive

        This method only takes care of getting a processed Report to the database and archive.

        It also tries to calculate the diff of the report (which uses commit info
            from th git provider), but it it fails to do so, it just moves on without such diff
        """
        log.debug("In save_report_results for commit: %s" % commit)
        commitid = commit.commitid
        try:
            installation_name_to_use = get_installation_name_for_owner_for_task(
                self.name, repository.owner
            )
            repository_service = get_repo_provider_service(
                repository, installation_name_to_use=installation_name_to_use
            )
            report.apply_diff(
                async_to_sync(repository_service.get_commit_diff)(commitid)
            )
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
                    parent_task=self.request.parent_id,
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
                    parent_task=self.request.parent_id,
                ),
                exc_info=True,
            )
        if pr is not None:
            try:
                commit.pullid = int(pr)
            except (ValueError, TypeError):
                log.warning(
                    "Cannot set PR value on commit",
                    extra=dict(
                        repoid=commit.repoid, commit=commit.commitid, pr_value=pr
                    ),
                )
        res = report_service.save_report(commit, report, report_code)
        db_session.commit()
        return res


RegisteredUploadTask = celery_app.register_task(UploadProcessorTask())
upload_processor_task = celery_app.tasks[RegisteredUploadTask.name]
