import logging
from typing import Any

import sentry_sdk
from asgiref.sync import async_to_sync
from celery.exceptions import CeleryError, SoftTimeLimitExceeded
from shared.celery_config import upload_processor_task_name
from shared.config import get_config
from shared.torngit.exceptions import TorngitError
from shared.yaml import UserYaml
from sqlalchemy.exc import SQLAlchemyError

from app import celery_app
from database.enums import CommitErrorTypes
from database.models import Commit, Upload
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME, Pull
from helpers.cache import cache
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.reports import delete_archive_setting
from helpers.save_commit_error import save_commit_error
from services.processing.intermediate import save_intermediate_report
from services.processing.state import ProcessingState
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
        *args,
        repoid,
        commitid,
        commit_yaml,
        arguments_list,
        arguments=None,
        report_code=None,
        **kwargs,
    ):
        repoid = int(repoid)
        log.info("Received upload processor task", extra={"arguments": arguments})

        # TODO(swatinem): this makes us forwards-compatible to remove `arguments_list` in the future
        if arguments and not arguments_list:
            arguments_list = [arguments]

        return self.process_upload(
            db_session=db_session,
            previous_results={},
            repoid=repoid,
            commitid=commitid,
            commit_yaml=commit_yaml,
            arguments_list=arguments_list,
            report_code=report_code,
        )

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

        report_service = ReportService(UserYaml(commit_yaml))
        archive_service = report_service.get_archive_service(commit.repository)
        report = Report()

        state = ProcessingState(repoid, commitid)
        upload_ids = [int(upload["upload_pk"]) for upload in arguments_list]
        # this in a noop in normal cases, but relevant for task retries:
        state.mark_uploads_as_processing(upload_ids)

        raw_reports: list[RawReportInfo] = []
        try:
            for arguments in arguments_list:
                upload_obj = (
                    db_session.query(Upload)
                    .filter_by(id_=arguments["upload_pk"])
                    .first()
                )
                log.info(
                    f"Processing individual report {arguments.get('reportid')}",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        arguments=arguments,
                        commit_yaml=commit_yaml,
                        upload=upload_obj.id_,
                        parent_task=self.request.parent_id,
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
                f"Finishing the processing of {n_processed} reports",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    parent_task=self.request.parent_id,
                ),
            )

            upload_id = int(arguments_list[0]["upload_pk"])
            save_intermediate_report(archive_service, commitid, upload_id, report)
            state.mark_upload_as_processed(upload_id)

            log.info(
                "Saved incremental report results to storage",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                ),
            )

            if raw_reports:
                self.postprocess_raw_reports(report_service, commit, raw_reports)

            log.info(
                f"Processed {n_processed} reports (+ {n_failed} failed)",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    commit_yaml=commit_yaml,
                    parent_task=self.request.parent_id,
                ),
            )

            processing_results: dict = {
                "processings_so_far": processings_so_far,
                "parallel_incremental_result": {"upload_pk": upload_id},
            }
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
        finally:
            # this is a noop in the success case, but makes sure unrecoverable errors
            # are not blocking later merge/notify stages
            state.clear_in_progress_uploads(upload_ids)

    @sentry_sdk.trace
    def process_individual_report(
        self,
        report_service: ReportService,
        commit: Commit,
        report: Report,
        upload: Upload,
        raw_report_info: RawReportInfo,
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

        report_service.update_upload_with_processing_result(upload, processing_result)

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
