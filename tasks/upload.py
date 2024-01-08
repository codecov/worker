import logging
import re
import uuid
from datetime import datetime, timedelta
from json import loads
from typing import Any, List, Mapping, Optional

from celery import chain, group
from redis import Redis
from redis.exceptions import LockError
from shared.celery_config import upload_task_name
from shared.config import get_config
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitRepoNotFoundError,
)
from shared.validation.exceptions import InvalidYamlException
from shared.yaml import UserYaml

from app import celery_app
from database.enums import CommitErrorTypes, ReportType
from database.models import Commit, CommitReport
from helpers.checkpoint_logger import _kwargs_key
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.save_commit_error import save_commit_error
from services.archive import ArchiveService
from services.bundle_analysis import BundleAnalysisReportService
from services.redis import Redis, download_archive_from_redis, get_redis_connection
from services.report import NotReadyToBuildReportYetError, ReportService
from services.repository import (
    create_webhook_on_provider,
    get_repo_provider_service,
    possibly_update_commit_from_provider_info,
    update_commit_from_provider_info,
)
from services.test_results import TestResultsReportService
from services.yaml import save_repo_yaml_to_database_if_needed
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from tasks.base import BaseCodecovTask
from tasks.bundle_analysis_notify import bundle_analysis_notify_task
from tasks.bundle_analysis_processor import bundle_analysis_processor_task
from tasks.test_results_processor import test_results_processor_task
from tasks.upload_finisher import upload_finisher_task
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME, upload_processor_task

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]").search
merged_pull = re.compile(r".*Merged in [^\s]+ \(pull request \#(\d+)\).*").match

CHUNK_SIZE = 3


class UploadContext:
    """
    Encapsulates the arguments passed to an upload task. This includes both the
    Celery task arguments as well as the arguments list passed via Redis.
    """

    def __init__(
        self,
        repoid: int,
        commitid: str,
        report_type: ReportType = ReportType.COVERAGE,
        report_code: Optional[str] = None,
        redis_connection: Optional[Redis] = None,
    ):
        self.repoid = repoid
        self.commitid = commitid
        self.report_type = report_type
        self.report_code = report_code
        self.redis_connection = redis_connection or get_redis_connection()

    def lock_name(self, lock_type: str):
        if self.report_type == ReportType.COVERAGE:
            # for backward compat this does not include the report type
            if lock_type == "upload_processing":
                return UPLOAD_PROCESSING_LOCK_NAME(self.repoid, self.commitid)
            else:
                return f"{lock_type}_lock_{self.repoid}_{self.commitid}"
        else:
            return f"{lock_type}_lock_{self.repoid}_{self.commitid}_{self.report_type.value}"

    @property
    def upload_location(self):
        if self.report_type == ReportType.COVERAGE:
            # for backward compat this does not include the report type
            return f"uploads/{self.repoid}/{self.commitid}"
        else:
            return f"uploads/{self.repoid}/{self.commitid}/{self.report_type.value}"

    def is_locked(self, lock_type: str) -> bool:
        lock_name = self.lock_name(lock_type)
        if self.redis_connection.get(lock_name):
            return True
        return False

    def is_currently_processing(self) -> bool:
        return self.is_locked("upload_processing")

    def has_pending_jobs(self) -> bool:
        if self.redis_connection.exists(self.upload_location):
            return True
        return False

    def last_upload_timestamp(self):
        if self.report_type == ReportType.COVERAGE:
            # for backward compat this does not include the report type
            redis_key = f"latest_upload/{self.repoid}/{self.commitid}"
        else:
            redis_key = (
                f"latest_upload/{self.repoid}/{self.commitid}/{self.report_type.value}"
            )
        return self.redis_connection.get(redis_key)

    def prepare_kwargs_for_retry(self, kwargs: dict):
        kwargs.update(
            {
                "repoid": self.repoid,
                "commitid": self.commitid,
                "report_type": self.report_type.value,
                "report_code": self.report_code,
            }
        )

    def arguments_list(self):
        """
        Retrieves a list of arguments from redis on the `uploads_list_key`, parses them
        and feeds them to the processing code.

        This function doesn't go infinite because it keeps emptying the respective key on redis.
        It will only go arbitrrily long if someone else keeps uploading more and more arguments
        to such list

        Args:
            redis_connection (Redis): An instance of a redis connection
            uploads_list_key (str): The key where the list is

        Yields:
            dict: A dict with the parameters to be passed
        """
        uploads_locations = [self.upload_location]
        for uploads_list_key in uploads_locations:
            log.debug("Fetching arguments from redis %s", uploads_list_key)
            while self.redis_connection.exists(uploads_list_key):
                arguments = self.redis_connection.lpop(uploads_list_key)
                if arguments:
                    yield loads(arguments)

    def normalize_arguments(self, commit: Commit, arguments: Mapping[str, Any]):
        """
        Normalizes and validates the argument list from the user.

        Does things like:

            - replacing a redis-stored value with a storage one (by doing an upload)
            - Removing unecessary sensitive information for the arguments
        """
        commit_sha = commit.commitid
        reportid = arguments.get("reportid")
        if arguments.get("redis_key"):
            archive_service = ArchiveService(commit.repository)
            redis_key = arguments.pop("redis_key")
            content = download_archive_from_redis(self.redis_connection, redis_key)
            written_path = archive_service.write_raw_upload(
                commit_sha, reportid, content
            )
            log.info(
                "Writing report content from redis to storage",
                extra=dict(
                    commit=commit.commitid, repoid=commit.repoid, path=written_path
                ),
            )
            arguments["url"] = written_path
        arguments.pop("token", None)
        return arguments


class UploadTask(BaseCodecovTask, name=upload_task_name):
    """The first of a series of tasks designed to process an `upload` made by the user

    This task is the first of three tasks, which run whenever a user makes
        an upload to `UploadHandler` (on the main app code)

    - UploadTask
    - UploadProcessorTask
    - UploadFinisherTask

    Each task has a purpose

    - UploadTask (this one)
        - Prepares the ground for the other tasks to run (view it as a compatibility layer between
            the old code and new)
        - Does things that only need to happen once per commit, and not per upload,
            like populating commit info and webhooks
    - UploadProcessorTask
        - Process each individual upload the user did (with some possible batching)
    - UploadFinisherTask
        - Does the finishing steps of processing, like deciding what tasks
            to schedule next (notifications)

    Now a little about this individual task.

    UploadTask has a specific purpose, it does all the 'pre-processing', for things that should be
        run outside the individual `upload` context, and is also the starter
        of the other tasks.

    The preprocessing tasks it does are:
        - Populating commit's info, in case this is the first time this commit is uploaded to our
            servers
        - Setup webhooks, in case this is the first time this repo has an upload on our servers
        - Fetch commit yaml from git provider, and possibly store it on the db (in case this
            is a commit on the repo default branch). This yaml is also passed and used on
            the other tasks, so they don't need to fetch it again

    The last thing this task does is schedule the other tasks. It works as a compatibility layer
        because the `UploadHandler` (on the main app code) pushes some important info to
        redis to be read here, and this task already takes all the relevant info from redis
        and pass them directly as parameters to the other tasks, so they don't have to manually
        deal with redis (since celery kind of automatically does the same behavior already)

    On the scheduling, this task does the following logic:
        - After fetching all uploads metadata (from redis), it splits the uploads in chunks of 3.
        - Each chunk goes to a `UploadProcessorTask`, and they are chained (as in `celery chain`)
        - At the end of the celery chain, we add one `UploadFinisherTask`. So after all processing,
            the finisher task does the finishing steps
        - In the end, the tasks are scheduled (sent to celery), and this task finishes

    """

    async def run_async(
        self,
        db_session,
        repoid,
        commitid,
        report_type="coverage",
        report_code=None,
        *args,
        **kwargs,
    ):
        # TODO: setup checkpoint flows for other coverage types
        if report_type == "coverage":
            # If we're a retry, kwargs will already have our first checkpoint.
            # If not, log it directly into kwargs so we can pass it onto other tasks
            checkpoints = checkpoints_from_kwargs(UploadFlow, kwargs).log(
                UploadFlow.UPLOAD_TASK_BEGIN, kwargs=kwargs, ignore_repeat=True
            )

        repoid = int(repoid)
        log.info(
            "Received upload task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                report_type=report_type,
                report_code=report_code,
            ),
        )
        upload_context = UploadContext(
            repoid=repoid,
            commitid=commitid,
            report_type=ReportType(report_type),
            report_code=report_code,
        )
        lock_name = upload_context.lock_name("upload")

        if upload_context.is_currently_processing() and self.request.retries == 0:
            log.info(
                "Currently processing upload. Retrying in 60s.",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    report_type=report_type,
                    has_pending_jobs=upload_context.has_pending_jobs(),
                ),
            )
            upload_context.prepare_kwargs_for_retry(kwargs)
            self.retry(countdown=60, kwargs=kwargs)

        try:
            with upload_context.redis_connection.lock(
                lock_name,
                timeout=max(300, self.hard_time_limit_task),
                blocking_timeout=5,
            ):
                return await self.run_async_within_lock(
                    db_session,
                    upload_context,
                    *args,
                    **kwargs,
                )
        except LockError:
            log.warning(
                "Unable to acquire lock for key %s.",
                lock_name,
                extra=dict(commit=commitid, repoid=repoid, report_type=report_type),
            )
            if not upload_context.has_pending_jobs():
                log.info(
                    "Not retrying since there are likely no jobs that need scheduling",
                    extra=dict(commit=commitid, repoid=repoid, report_type=report_type),
                )
                checkpoints.log(UploadFlow.NO_PENDING_JOBS)
                return {
                    "was_setup": False,
                    "was_updated": False,
                    "tasks_were_scheduled": False,
                }
            if self.request.retries > 1:
                log.info(
                    "Not retrying since we already had too many retries",
                    extra=dict(commit=commitid, repoid=repoid, report_type=report_type),
                )
                checkpoints.log(UploadFlow.TOO_MANY_RETRIES)
                return {
                    "was_setup": False,
                    "was_updated": False,
                    "tasks_were_scheduled": False,
                    "reason": "too_many_retries",
                }
            retry_countdown = 20 * 2**self.request.retries
            log.warning(
                "Retrying upload",
                extra=dict(
                    commit=commitid,
                    repoid=repoid,
                    report_type=report_type,
                    countdown=int(retry_countdown),
                ),
            )
            upload_context.prepare_kwargs_for_retry(kwargs)
            self.retry(max_retries=3, countdown=retry_countdown, kwargs=kwargs)

    async def run_async_within_lock(
        self,
        db_session,
        upload_context: UploadContext,
        *args,
        **kwargs,
    ):
        log.info(
            "Starting processing of report",
            extra=dict(
                repoid=upload_context.repoid,
                commit=upload_context.commitid,
                report_type=upload_context.report_type.value,
                report_code=upload_context.report_code,
            ),
        )
        if not upload_context.has_pending_jobs():
            log.info("No pending jobs. Upload task is done.")
            return {
                "was_setup": False,
                "was_updated": False,
                "tasks_were_scheduled": False,
            }

        upload_processing_delay = get_config("setup", "upload_processing_delay")
        if upload_processing_delay is not None:
            upload_processing_delay = int(upload_processing_delay)
            last_upload_timestamp = upload_context.last_upload_timestamp()
            if last_upload_timestamp is not None:
                last_upload = datetime.fromtimestamp(float(last_upload_timestamp))
                if (
                    datetime.utcnow() - timedelta(seconds=upload_processing_delay)
                    < last_upload
                ):
                    retry_countdown = max(30, upload_processing_delay)
                    log.info(
                        "Retrying due to very recent uploads.",
                        extra=dict(
                            repoid=upload_context.repoid,
                            commit=upload_context.commitid,
                            report_type=upload_context.report_type.value,
                            countdown=retry_countdown,
                        ),
                    )
                    upload_context.prepare_kwargs_for_retry(kwargs)
                    self.retry(countdown=retry_countdown, kwargs=kwargs)

        try:
            checkpoints = checkpoints_from_kwargs(UploadFlow, kwargs)
            checkpoints.log(UploadFlow.PROCESSING_BEGIN)
        except ValueError as e:
            log.warning(f"CheckpointLogger failed to log/submit", extra=dict(error=e))

        repoid = upload_context.repoid
        commitid = upload_context.commitid
        report_type = upload_context.report_type
        report_code = upload_context.report_code

        commit = None
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        repository = commit.repository
        repository.updatestamp = datetime.now()
        repository_service = None
        was_updated, was_setup = False, False
        try:
            repository_service = get_repo_provider_service(repository, commit)
            was_updated = await possibly_update_commit_from_provider_info(
                commit, repository_service
            )
            was_setup = await self.possibly_setup_webhooks(commit, repository_service)
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit,
                error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
                error_params=dict(repoid=repoid, repository_service=repository_service),
            )

            log.warning(
                "Unable to reach git provider because repo doesn't have a valid bot",
                extra=dict(repoid=repoid, commit=commitid),
            )
        except TorngitRepoNotFoundError:
            log.warning(
                "Unable to reach git provider because this specific bot/integration can't see that repository",
                extra=dict(repoid=repoid, commit=commitid),
            )
        except TorngitClientError:
            log.warning(
                "Unable to reach git provider because there was a 4xx error",
                extra=dict(repoid=repoid, commit=commitid),
                exc_info=True,
            )
        if repository_service:
            commit_yaml = await self.fetch_commit_yaml_and_possibly_store(
                commit, repository_service
            )
        else:
            commit_yaml = UserYaml.get_final_yaml(
                owner_yaml=repository.owner.yaml,
                repo_yaml=repository.yaml,
                commit_yaml=None,
                ownerid=repository.owner.ownerid,
            )

        if report_type == ReportType.COVERAGE:
            # TODO: consider renaming class to `CoverageReportService`
            report_service = ReportService(commit_yaml)
        elif report_type == ReportType.BUNDLE_ANALYSIS:
            report_service = BundleAnalysisReportService(commit_yaml)
        elif report_type == ReportType.TEST_RESULTS:
            report_service = TestResultsReportService(commit_yaml)
        else:
            raise NotImplementedError(f"no report service for: {report_type.value}")

        try:
            log.info(
                "Initializing and saving report",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    report_type=report_type.value,
                    report_code=report_code,
                ),
            )
            commit_report = await report_service.initialize_and_save_report(
                commit,
                report_code,
            )
        except NotReadyToBuildReportYetError:
            log.warning(
                "Commit not yet ready to build its initial report. Retrying in 60s.",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            upload_context.prepare_kwargs_for_retry(kwargs)
            self.retry(countdown=60, kwargs=kwargs)
        argument_list = []
        for arguments in upload_context.arguments_list():
            normalized_arguments = upload_context.normalize_arguments(commit, arguments)
            if "upload_id" in normalized_arguments:
                upload = report_service.fetch_report_upload(
                    commit_report, normalized_arguments["upload_id"]
                )
            else:
                upload = report_service.create_report_upload(
                    normalized_arguments, commit_report
                )
            normalized_arguments["upload_pk"] = upload.id_
            argument_list.append(normalized_arguments)
        if argument_list:
            db_session.commit()
            self.schedule_task(
                commit, commit_yaml, argument_list, commit_report, checkpoints
            )
        else:
            checkpoints.log(UploadFlow.INITIAL_PROCESSING_COMPLETE)
            log.info(
                "Not scheduling task because there were no arguments were found on redis",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    argument_list=argument_list,
                ),
            )
        return {"was_setup": was_setup, "was_updated": was_updated}

    async def fetch_commit_yaml_and_possibly_store(self, commit, repository_service):
        repository = commit.repository
        try:
            log.info(
                "Fetching commit yaml from provider for commit",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            commit_yaml = await fetch_commit_yaml_from_provider(
                commit, repository_service
            )
            save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        except InvalidYamlException as ex:
            save_commit_error(
                commit,
                error_code=CommitErrorTypes.INVALID_YAML.value,
                error_params=dict(
                    repoid=repository.repoid,
                    commit=commit.commitid,
                    error_location=ex.error_location,
                ),
            )
            log.warning(
                "Unable to use yaml from commit because it is invalid",
                extra=dict(
                    repoid=repository.repoid,
                    commit=commit.commitid,
                    error_location=ex.error_location,
                ),
                exc_info=True,
            )
            commit_yaml = None
        except TorngitClientError:
            log.warning(
                "Unable to use yaml from commit because it cannot be fetched",
                extra=dict(repoid=repository.repoid, commit=commit.commitid),
                exc_info=True,
            )
            commit_yaml = None
        return UserYaml.get_final_yaml(
            owner_yaml=repository.owner.yaml,
            repo_yaml=repository.yaml,
            commit_yaml=commit_yaml,
            ownerid=repository.owner.ownerid,
        )

    def schedule_task(
        self,
        commit,
        commit_yaml,
        argument_list,
        commit_report: CommitReport,
        checkpoints=None,
    ):
        commit_yaml = commit_yaml.to_dict()

        res = None
        if (
            commit_report.report_type is None
            or commit_report.report_type == ReportType.COVERAGE.value
        ):
            res = self._schedule_coverage_processing_task(
                commit,
                commit_yaml,
                argument_list,
                commit_report,
                checkpoints=checkpoints,
            )
        elif commit_report.report_type == ReportType.BUNDLE_ANALYSIS.value:
            res = self._schedule_bundle_analysis_processing_task(
                commit,
                commit_yaml,
                argument_list,
            )
        elif commit_report.report_type == ReportType.TEST_RESULTS.value:
            res = self._schedule_test_results_processing_task(
                commit, commit_yaml, argument_list, commit_report, checkpoints
            )

        if res:
            return res

        log.info(
            "Not scheduling task because there were no reports to be processed found",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
                argument_list=argument_list,
            ),
        )
        return None

    def _schedule_coverage_processing_task(
        self, commit, commit_yaml, argument_list, commit_report, checkpoints=None
    ):
        chain_to_call = []
        for i in range(0, len(argument_list), CHUNK_SIZE):
            chunk = argument_list[i : i + CHUNK_SIZE]
            if chunk:
                sig = upload_processor_task.signature(
                    args=({},) if i == 0 else (),
                    kwargs=dict(
                        repoid=commit.repoid,
                        commitid=commit.commitid,
                        commit_yaml=commit_yaml,
                        arguments_list=chunk,
                        report_code=commit_report.code,
                    ),
                )
                chain_to_call.append(sig)
        if chain_to_call:
            checkpoint_data = None
            if checkpoints:
                checkpoints.log(UploadFlow.INITIAL_PROCESSING_COMPLETE)
                checkpoint_data = checkpoints.data

            finish_sig = upload_finisher_task.signature(
                kwargs={
                    "repoid": commit.repoid,
                    "commitid": commit.commitid,
                    "commit_yaml": commit_yaml,
                    "report_code": commit_report.code,
                    _kwargs_key(UploadFlow): checkpoint_data,
                },
            )
            chain_to_call.append(finish_sig)
            res = chain(*chain_to_call).apply_async()

            log.info(
                "Scheduling task for %s different reports",
                len(argument_list),
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    argument_list=argument_list,
                    number_arguments=len(argument_list),
                    scheduled_task_ids=res.as_tuple(),
                ),
            )
            return res

    def _schedule_bundle_analysis_processing_task(
        self,
        commit: Commit,
        commit_yaml: UserYaml,
        argument_list: List[dict],
    ):
        task_signatures = [
            bundle_analysis_processor_task.signature(
                args=({},) if i == 0 else (),  # to support Celery `chain`
                kwargs=dict(
                    repoid=commit.repoid,
                    commitid=commit.commitid,
                    commit_yaml=commit_yaml,
                    params=params,
                ),
            )
            for i, params in enumerate(argument_list)
        ]

        # it might make sense to eventually have a "finisher" task that
        # does whatever extra stuff + enqueues a notify
        notify_sig = bundle_analysis_notify_task.signature(
            kwargs={
                "repoid": commit.repoid,
                "commitid": commit.commitid,
                "commit_yaml": commit_yaml,
            },
        )
        task_signatures.append(notify_sig)

        res = chain(*task_signatures).apply_async()
        log.info(
            "Scheduling bundle analysis processor tasks",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
                argument_list=argument_list,
                number_arguments=len(argument_list),
                scheduled_task_ids=res.as_tuple(),
            ),
        )
        return res

    def _schedule_test_results_processing_task(
        self,
        commit,
        commit_yaml,
        argument_list,
        commit_report,
        checkpoints=None,
    ):
        processor_task_group = []
        for i in range(0, len(argument_list), CHUNK_SIZE):
            chunk = argument_list[i : i + CHUNK_SIZE]
            if chunk:
                sig = test_results_processor_task.signature(
                    args=(),
                    kwargs=dict(
                        repoid=commit.repoid,
                        commitid=commit.commitid,
                        commit_yaml=commit_yaml,
                        arguments_list=chunk,
                        report_code=commit_report.code,
                    ),
                )
                processor_task_group.append(sig)
        if processor_task_group:
            checkpoint_data = None
            if checkpoints:
                checkpoints.log(UploadFlow.INITIAL_PROCESSING_COMPLETE)
                checkpoint_data = checkpoints.data

            res = group(
                processor_task_group,
            ).apply_async()

            log.info(
                "Scheduling task for %s different reports",
                len(argument_list),
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    argument_list=argument_list,
                    number_arguments=len(argument_list),
                    scheduled_task_ids=res.as_tuple(),
                ),
            )
            return res
        log.info(
            "Not scheduling task because there were no reports to be processed found",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
                argument_list=argument_list,
            ),
        )
        return None

    async def possibly_setup_webhooks(self, commit, repository_service):
        repository = commit.repository
        repo_data = repository_service.data
        should_post_webhook = (
            not repository.using_integration
            and not repository.hookid
            and hasattr(repository_service, "post_webhook")
        )

        # try to add webhook
        if should_post_webhook:
            log.info(
                "Setting up webhook",
                extra=dict(repoid=repository.repoid, commit=commit.commitid),
            )
            try:
                if repository_service.service in ["gitlab", "gitlab_enterprise"]:
                    # we use per-repo webhook secrets in this case
                    webhook_secret = repository.webhook_secret or str(uuid.uuid4())
                else:
                    # service-level config value will be used instead in this case
                    webhook_secret = None
                hook_result = await create_webhook_on_provider(
                    repository_service, webhook_secret=webhook_secret
                )
                hookid = hook_result["id"]
                log.info(
                    "Registered hook",
                    extra=dict(
                        repoid=commit.repoid, commit=commit.commitid, hookid=hookid
                    ),
                )
                repository.hookid = hookid
                if webhook_secret is not None:
                    repository.webhook_secret = webhook_secret
                repo_data["repo"]["hookid"] = hookid
                return True
            except TorngitClientError:
                log.warning(
                    "Failed to create project webhook",
                    extra=dict(repoid=repository.repoid, commit=commit.commitid),
                )
        return False


RegisteredUploadTask = celery_app.register_task(UploadTask())
upload_task = celery_app.tasks[RegisteredUploadTask.name]
