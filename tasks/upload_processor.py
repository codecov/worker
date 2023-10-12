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

    def schedule_for_later_try(self, max_retries=5):
        retry_in = FIRST_RETRY_DELAY * 3**self.request.retries
        self.retry(max_retries=max_retries, countdown=retry_in)

    async def run_async(
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
            extra=dict(repoid=repoid, commit=commitid),
        )
        lock_name = f"upload_processing_lock_{repoid}_{commitid}"
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
                actual_arguments_list = deepcopy(arguments_list)
                return await self.process_async_within_lock(
                    db_session=db_session,
                    previous_results=previous_results,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    arguments_list=actual_arguments_list,
                    report_code=report_code,
                    parent_task=self.request.parent_id,
                    **kwargs,
                )
        except LockError:
            max_retry = 200 * 3**self.request.retries
            retry_in = min(random.randint(max_retry / 2, max_retry), 60 * 60 * 5)
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
            self.retry(max_retries=5, countdown=retry_in)

    async def process_async_within_lock(
        self,
        *,
        db_session,
        previous_results,
        repoid,
        commitid,
        commit_yaml,
        arguments_list,
        report_code,
        **kwargs,
    ):
        commit_yaml = UserYaml(commit_yaml)
        log.info(
            "Obtained upload processing lock, starting",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                parent_task=self.request.parent_id,
                report_code=report_code,
            ),
        )
        processings_so_far = previous_results.get("processings_so_far", [])
        commit = None
        n_processed = 0
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        repository = commit.repository
        pr = None
        try_later = []
        report_service = ReportService(commit_yaml)

        with metrics.timer(f"{self.metrics_prefix}.build_original_report"):
            report = report_service.get_existing_report_for_commit(
                commit, report_code=report_code
            )
            if report is None:
                log.info(
                    "No existing report for commit", extra=dict(commit=commit.commitid)
                )
                report = Report()
        try:
            for arguments in arguments_list:
                pr = arguments.get("pr")
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
                individual_info = {"arguments": arguments.copy()}
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
                    individual_info.update(result)
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
                if individual_info.get("successful"):
                    report = individual_info.pop("report")
                    n_processed += 1
                processings_so_far.append(individual_info)
            log.info(
                "Finishing the processing of %d reports",
                n_processed,
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    parent_task=self.request.parent_id,
                ),
            )
            with metrics.timer(f"{self.metrics_prefix}.save_report_results"):
                results_dict = await self.save_report_results(
                    db_session,
                    report_service,
                    repository,
                    commit,
                    report,
                    pr,
                    report_code,
                )
            for processed_individual_report in processings_so_far:
                deleted_archive = self._possibly_delete_archive(
                    processed_individual_report, report_service, commit
                )
                if not deleted_archive:
                    self._rewrite_raw_report_readable(
                        processed_individual_report, report_service, commit
                    )
                processed_individual_report.pop("upload_obj", None)
                processed_individual_report.pop("raw_report", None)
            log.info(
                "Processed %d reports",
                n_processed,
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    commit_yaml=commit_yaml.to_dict(),
                    url=results_dict.get("url"),
                    parent_task=self.request.parent_id,
                ),
            )
            return {"processings_so_far": processings_so_far}
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

    async def save_report_results(
        self,
        db_session,
        report_service,
        repository,
        commit,
        report,
        pr,
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
            repository_service = get_repo_provider_service(repository, commit)
            report.apply_diff(await repository_service.get_commit_diff(commitid))
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
