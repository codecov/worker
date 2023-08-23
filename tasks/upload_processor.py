import logging
import random
import re
from copy import deepcopy
from typing import Optional

import sentry_sdk
from celery.exceptions import CeleryError, SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.celery_config import upload_processor_task_name
from shared.config import get_config
from shared.reports.enums import UploadState
from shared.torngit.exceptions import TorngitError
from shared.yaml import UserYaml
from sqlalchemy.exc import SQLAlchemyError

from app import celery_app
from database.enums import CommitErrorTypes
from database.models import Commit, Upload
from helpers.metrics import metrics
from helpers.save_commit_error import save_commit_error
from services.bots import RepositoryWithoutValidBotError
from services.redis import get_redis_connection
from services.report import ProcessingResult, Report, ReportService
from services.repository import get_repo_provider_service
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]").search
merged_pull = re.compile(r".*Merged in [^\s]+ \(pull request \#(\d+)\).*").match
FIRST_RETRY_DELAY = 20


class UploadProcessorTask(BaseCodecovTask):
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

    name = upload_processor_task_name

    acks_late = get_config("setup", "tasks", "upload", "acks_late", default=False)

    def schedule_for_later_try(self, max_retries=5):
        retry_in = FIRST_RETRY_DELAY * 3**self.request.retries
        self.retry(max_retries=max_retries, countdown=retry_in)

    async def run_async(
        self,
        db_session,
        previous_results,  # TODO do we need this
        *,
        repoid,
        commitid,
        commit_yaml,
        arguments_list,
        chunk_idx,
        report_code=None,
        **kwargs,
    ):
        repoid = int(repoid)
        log.info(
            "Received upload processor task",
            extra=dict(repoid=repoid, commit=commitid),
        )
        lock_name = f"upload_processing_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        actual_arguments_list = deepcopy(arguments_list)
        return await self.process_async_within_lock(
            db_session=db_session,
            previous_results=previous_results,
            repoid=repoid,
            commitid=commitid,
            commit_yaml=commit_yaml,
            arguments_list=actual_arguments_list,
            chunk_idx=chunk_idx,
            report_code=report_code,
            parent_task=self.request.parent_id,
            **kwargs,
        )

    async def process_async_within_lock(
        self,
        *,
        db_session,
        previous_results,
        repoid,
        commitid,
        commit_yaml,
        arguments_list,
        chunk_idx,
        report_code,
        **kwargs,
    ):
        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database"

        repository = commit.repository
        commit_yaml = UserYaml(commit_yaml)
        report_service = ReportService(commit_yaml)

        report = Report()
        processing_results = []
        try:
            for arguments in arguments_list:
                upload_obj = (
                    db_session.query(Upload)
                    .filter_by(id_=arguments.get("upload_pk"))
                    .first()
                )
                log.info(
                    "Processing individual report %s",
                    arguments.get("reportid"),
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        arguments=arguments,
                        commit_yaml=commit_yaml.to_dict(),
                        upload=upload_obj.id_,
                        parent_task=self.request.parent_id,
                    ),
                )

                try:
                    arguments_commitid = arguments.pop("commit", None)
                    if arguments_commitid:
                        assert arguments_commitid == commit.commitid
                    with metrics.timer(
                        f"{self.metrics_prefix}.process_individual_report"
                    ):
                        result = self.process_individual_report(
                            report_service, commit, report, upload_obj
                        )
                except (CeleryError, SoftTimeLimitExceeded, SQLAlchemyError):
                    raise
                except Exception:
                    log.exception(
                        "Unable to process report %s",
                        arguments.get("reportid"),
                        extra=dict(
                            commit_yaml=commit_yaml.to_dict(),
                            repoid=repoid,
                            commit=commitid,
                            arguments=arguments,
                            parent_task=self.request.parent_id,
                        ),
                    )
                    upload_obj.state_id = UploadState.ERROR.db_id
                    upload_obj.state = "error"
                    raise
                if result.get("successful"):
                    report = result.pop("report")
                    processing_results.append(
                        {
                            "upload_obj": result.pop("upload_obj"),
                            "raw_report": result.pop("raw_report"),
                        }
                    )
            log.info(
                "Finishing the processing of %d reports",
                len(arguments_list),
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    parent_task=self.request.parent_id,
                ),
            )

            # saving incremental result to archive storage
            # upload finisher task will combine
            chunks = report.to_archive().encode()
            _, files_and_sessions = report.to_database()

            chunks_url = archive_service.write_chunks(
                commitid, chunks, report_code=f"incremental/chunk{chunk_idx}.txt"
            )
            files_and_sessions_url = archive_service.write_chunks(
                commitid,
                files_and_sessions,
                report_code=f"incremental/files_and_sessions{chunk_idx}.txt",
            )

            incremental_result = {
                "idx": chunk_idx,
                "chunks_path": chunks_url,
                "files_sessions_path": files_and_sessions_url,
            }

            for processed_upload in processing_results:
                deleted_archive = self._possibly_delete_archive(
                    processed_upload, report_service, commit
                )
                if not deleted_archive:
                    self._rewrite_raw_report_readable(
                        processed_upload, report_service, commit
                    )

            return incremental_result
        except CeleryError:
            raise
        except Exception:
            commit.state = "error"
            log.exception(
                "Could not properly process commit",
                extra=dict(repoid=repoid, commit=commitid, arguments=try_later),
            )
            raise

    @sentry_sdk.trace
    def process_individual_report(self, report_service, commit, report, upload_obj):
        processing_result = self.do_process_individual_report(
            report_service, report, upload=upload_obj
        )
        if (
            processing_result.error is not None
            and processing_result.error.is_retryable
            and self.request.retries == 0
        ):
            log.info(
                "Scheduling a retry in %d due to retryable error",  # TODO: check if we have this in the logs
                FIRST_RETRY_DELAY,
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    upload_id=upload_obj.id,
                    processing_result_error_code=processing_result.error.code,
                    processing_result_error_params=processing_result.error.params,
                    parent_task=self.request.parent_id,
                ),
            )
            self.schedule_for_later_try()
        report_service.update_upload_with_processing_result(
            upload_obj, processing_result
        )
        return processing_result.as_dict()

    def do_process_individual_report(
        self,
        report_service: ReportService,
        current_report: Optional[Report],
        *,
        upload: Upload,
    ):
        res: ProcessingResult = report_service.build_report_from_raw_content(
            current_report, upload
        )
        return res

    def should_delete_archive(self, commit_yaml):
        if get_config("services", "minio", "expire_raw_after_n_days"):
            return True
        return not read_yaml_field(
            commit_yaml, ("codecov", "archive", "uploads"), _else=True
        )

    def _possibly_delete_archive(
        self, processing_result: dict, report_service: ReportService, commit: Commit
    ):
        if self.should_delete_archive(report_service.current_yaml):
            upload = processing_result.get("upload_obj")
            archive_url = upload.storage_path
            if archive_url and not archive_url.startswith("http"):
                log.info(
                    "Deleting uploaded file as requested",
                    extra=dict(
                        archive_url=archive_url,
                        commit=commit.commitid,
                        upload=upload.external_id,
                        parent_task=self.request.parent_id,
                    ),
                )
                archive_service = report_service.get_archive_service(commit.repository)
                archive_service.delete_file(archive_url)
                return True
        return False

    def _rewrite_raw_report_readable(
        self,
        processing_result: dict,
        report_service: ReportService,
        commit: Commit,
    ):
        raw_report = processing_result.get("raw_report")
        if raw_report:
            upload = processing_result.get("upload_obj")
            archive_url = upload.storage_path
            log.info(
                "Re-writing raw report in readable format",
                extra=dict(
                    archive_url=archive_url,
                    commit=commit.commitid,
                    upload=upload.external_id,
                    parent_task=self.request.parent_id,
                ),
            )
            archive_service = report_service.get_archive_service(commit.repository)
            archive_service.write_file(archive_url, raw_report.content().getvalue())


RegisteredUploadTask = celery_app.register_task(UploadProcessorTask())
upload_processor_task = celery_app.tasks[RegisteredUploadTask.name]
