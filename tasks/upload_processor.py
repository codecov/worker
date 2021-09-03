import logging
import random
import re
from copy import deepcopy
from typing import Optional

from celery.exceptions import CeleryError, SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.celery_config import upload_processor_task_name
from shared.config import get_config
from shared.storage.exceptions import FileNotInStorageError
from shared.torngit.exceptions import TorngitClientError
from shared.yaml import UserYaml
from sqlalchemy.exc import SQLAlchemyError

from app import celery_app
from database.models import Commit, Upload
from helpers.metrics import metrics
from services.bots import RepositoryWithoutValidBotError
from services.redis import get_redis_connection
from services.report import Report, ReportService
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

    def schedule_for_later_try(self, max_retries=5):
        retry_in = FIRST_RETRY_DELAY * 3 ** self.request.retries
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
        **kwargs,
    ):
        repoid = int(repoid)
        log.debug("In run_async for repoid %d and commit %s", repoid, commitid)
        lock_name = f"upload_processing_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
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
                    **kwargs,
                )
        except LockError:
            log.warning(
                "Unable to acquire lock for key %s. Retrying",
                lock_name,
                extra=dict(
                    commit=commitid, repoid=repoid, number_retries=self.request.retries
                ),
            )
            max_retry = 200 * 3 ** self.request.retries
            retry_in = min(random.randint(max_retry / 2, max_retry), 60 * 60 * 5)
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
        **kwargs,
    ):
        commit_yaml = UserYaml(commit_yaml)
        log.debug("Obtained lock for repoid %d and commit %s", repoid, commitid)
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
        should_delete_archive = self.should_delete_archive(commit_yaml)
        try_later = []
        report_service = ReportService(commit_yaml)

        with metrics.timer(f"{self.metrics_prefix}.build_original_report"):
            report = report_service.get_existing_report_for_commit(commit)
            if report is None:
                report = Report()
        try:
            for arguments in arguments_list:
                pr = arguments.get("pr")
                log.info(
                    "Processing individual report %s",
                    arguments.get("reportid"),
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        arguments=arguments,
                        commit_yaml=commit_yaml.to_dict(),
                    ),
                )
                individual_info = {"arguments": arguments.copy()}
                try:
                    arguments_commitid = arguments.pop("commit", None)
                    if arguments_commitid:
                        assert arguments_commitid == commit.commitid
                    upload_obj = (
                        db_session.query(Upload)
                        .filter_by(id_=arguments.get("upload_pk"))
                        .first()
                    )
                    with metrics.timer(
                        f"{self.metrics_prefix}.process_individual_report"
                    ):
                        result = self.process_individual_report(
                            report_service,
                            commit,
                            report,
                            upload_obj,
                            should_delete_archive,
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
                        ),
                    )
                    self.schedule_for_later_try(max_retries=1)
                if individual_info.get("successful"):
                    report = individual_info.pop("report")
                    n_processed += 1
                processings_so_far.append(individual_info)
            log.info(
                "Finishing the processing of %d reports",
                n_processed,
                extra=dict(repoid=repoid, commit=commitid),
            )
            with metrics.timer(f"{self.metrics_prefix}.save_report_results"):
                results_dict = await self.save_report_results(
                    db_session, report_service, repository, commit, report, pr
                )
            log.info(
                "Processed %d reports",
                n_processed,
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    commit_yaml=commit_yaml.to_dict(),
                    url=results_dict.get("url"),
                ),
            )
            return {
                "processings_so_far": processings_so_far,
            }
        except CeleryError:
            raise
        except Exception:
            commit.state = "error"
            log.exception(
                "Could not properly process commit",
                extra=dict(repoid=repoid, commit=commitid, arguments=try_later),
            )
            raise

    def process_individual_report(
        self, report_service, commit, report, upload_obj, should_delete_archive,
    ):
        processing_result = self.do_process_individual_report(
            report_service, commit, report, should_delete_archive, upload=upload_obj
        )
        if (
            processing_result.error is not None
            and processing_result.error.is_retryable
            and self.request.retries == 0
        ):
            log.info(
                "Scheduling a retry in %d due to retryable error",
                FIRST_RETRY_DELAY,
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    upload_id=upload_obj.id,
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
        commit: Commit,
        current_report: Optional[Report],
        should_delete_archive: bool,
        *,
        upload: Upload,
    ):
        res = report_service.build_report_from_raw_content(current_report, upload)
        archive_url = upload.storage_path
        if should_delete_archive and archive_url and not archive_url.startswith("http"):
            log.info(
                "Deleting uploaded file as requested",
                extra=dict(archive_url=archive_url),
            )
            archive_service = report_service.get_archive_service(commit.repository)
            archive_service.delete_file(archive_url)
            archive_url = None
        return res

    def should_delete_archive(self, commit_yaml):
        if get_config("services", "minio", "expire_raw_after_n_days"):
            return True
        return not read_yaml_field(
            commit_yaml, ("codecov", "archive", "uploads"), _else=True
        )

    async def save_report_results(
        self, db_session, report_service, repository, commit, report, pr
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
        except TorngitClientError:
            # When this happens, we have that commit.totals["diff"] is not available.
            # Since there is no way to calculate such diff without the git commit,
            # then we assume having the rest of the report saved there is better than the
            # alternative of refusing an otherwise "good" report because of the lack of diff
            log.warning(
                "Could not apply diff to report because there was a 4xx error",
                extra=dict(repoid=commit.repoid, commit=commit.commitid,),
                exc_info=True,
            )
        except RepositoryWithoutValidBotError:
            log.warning(
                "Could not apply diff to report because there is no valid bot found for that repo",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
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
        res = report_service.save_report(commit, report)
        db_session.commit()
        return res


RegisteredUploadTask = celery_app.register_task(UploadProcessorTask())
upload_processor_task = celery_app.tasks[RegisteredUploadTask.name]
