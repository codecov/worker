import logging
import re
from datetime import datetime, timedelta
from json import loads
from typing import Any, Mapping

from celery import chain
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
from database.models import Commit
from helpers.exceptions import RepositoryWithoutValidBotError
from services.archive import ArchiveService
from services.redis import Redis, download_archive_from_redis, get_redis_connection
from services.report import NotReadyToBuildReportYetError, ReportService
from services.repository import (
    create_webhook_on_provider,
    get_repo_provider_service,
    update_commit_from_provider_info,
)
from services.yaml import save_repo_yaml_to_database_if_needed
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from tasks.base import BaseCodecovTask
from tasks.upload_finisher import upload_finisher_task
from tasks.upload_processor import upload_processor_task

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]").search
merged_pull = re.compile(r".*Merged in [^\s]+ \(pull request \#(\d+)\).*").match

CHUNK_SIZE = 3


class UploadTask(BaseCodecovTask):
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

    name = upload_task_name

    def has_pending_jobs(self, redis_connection, repoid, commitid) -> bool:
        uploads_locations = [
            f"uploads/{repoid}/{commitid}",
        ]
        for uploads_list_key in uploads_locations:
            if redis_connection.exists(uploads_list_key):
                return True
        return False

    def lists_of_arguments(self, redis_connection, repoid, commitid):
        """Retrieves a list of arguments from redis on the `uploads_list_key`, parses them
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
        uploads_locations = [
            f"uploads/{repoid}/{commitid}",
        ]
        for uploads_list_key in uploads_locations:
            log.debug("Fetching arguments from redis %s", uploads_list_key)
            while redis_connection.exists(uploads_list_key):
                arguments = redis_connection.lpop(uploads_list_key)
                if arguments:
                    yield loads(arguments)

    def is_currently_processing(self, redis_connection, repoid, commitid):
        upload_processing_lock_name = f"upload_processing_lock_{repoid}_{commitid}"
        if redis_connection.get(upload_processing_lock_name):
            return True
        return False

    async def run_async(self, db_session, repoid, commitid, *args, **kwargs):
        log.info("Received upload task", extra=dict(repoid=repoid, commit=commitid))
        repoid = int(repoid)
        lock_name = f"upload_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        if (
            self.is_currently_processing(redis_connection, repoid, commitid)
            and self.request.retries == 0
        ):
            log.info(
                "Waiting longer to collect more jobs for processing",
                extra=dict(
                    repoid=repoid,
                    commtid=commitid,
                    has_pending_jobs=self.has_pending_jobs(
                        redis_connection, repoid, commitid
                    ),
                ),
            )
            self.retry(countdown=60)
        try:
            with redis_connection.lock(
                lock_name,
                timeout=max(300, self.hard_time_limit_task),
                blocking_timeout=5,
            ):
                return await self.run_async_within_lock(
                    db_session, redis_connection, repoid, commitid, *args, **kwargs
                )
        except LockError:
            log.warning(
                "Unable to acquire lock for key %s. Retrying",
                lock_name,
                extra=dict(commit=commitid, repoid=repoid),
            )
            if not self.has_pending_jobs(redis_connection, repoid, commitid):
                log.info(
                    "Not retrying since there are likely no jobs that need scheduling",
                    extra=dict(commit=commitid, repoid=repoid),
                )
                return {
                    "was_setup": False,
                    "was_updated": False,
                    "tasks_were_scheduled": False,
                }
            if self.request.retries > 1:
                log.info(
                    "Not retrying since we already had too many retries",
                    extra=dict(commit=commitid, repoid=repoid),
                )
                return {
                    "was_setup": False,
                    "was_updated": False,
                    "tasks_were_scheduled": False,
                    "reason": "too_many_retries",
                }
            self.retry(max_retries=3, countdown=20 * 2 ** self.request.retries)

    async def run_async_within_lock(
        self, db_session, redis_connection, repoid, commitid, *args, **kwargs
    ):
        log.info(
            "Starting processing of report", extra=dict(repoid=repoid, commit=commitid)
        )
        if not self.has_pending_jobs(redis_connection, repoid, commitid):
            return {
                "was_setup": False,
                "was_updated": False,
                "tasks_were_scheduled": False,
            }
        upload_processing_delay = get_config("setup", "upload_processing_delay")
        if upload_processing_delay is not None:
            upload_processing_delay = int(upload_processing_delay)
            last_upload_timestamp = redis_connection.get(
                f"latest_upload/{repoid}/{commitid}"
            )
            if last_upload_timestamp is not None:
                last_upload = datetime.fromtimestamp(float(last_upload_timestamp))
                if (
                    datetime.utcnow() - timedelta(seconds=upload_processing_delay)
                    < last_upload
                ):
                    log.info(
                        "Retrying due to very recent uploads",
                        extra=dict(repoid=repoid, commit=commitid),
                    )
                    self.retry(countdown=max(30, upload_processing_delay))
        commit = None
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        repository = commit.repository
        repository_service = None
        was_updated, was_setup = False, False
        try:
            repository_service = get_repo_provider_service(repository, commit)
            was_updated = await self.possibly_update_commit_from_provider_info(
                commit, repository_service
            )
            was_setup = await self.possibly_setup_webhooks(commit, repository_service)
        except RepositoryWithoutValidBotError:
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
            )
        report_service = ReportService(commit_yaml)
        try:
            commit_report = report_service.initialize_and_save_report(commit)
        except NotReadyToBuildReportYetError:
            log.warning(
                "Commit not yet ready to build its initial report",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            self.retry(countdown=60)
        argument_list = []
        for arguments in self.lists_of_arguments(redis_connection, repoid, commitid):
            normalized_arguments = self.normalize_upload_arguments(
                commit, arguments, redis_connection
            )
            upload = report_service.create_report_upload(
                normalized_arguments, commit_report
            )
            normalized_arguments["upload_pk"] = upload.id_
            argument_list.append(normalized_arguments)
        if argument_list:
            db_session.commit()
            self.schedule_task(commit, commit_yaml, argument_list)
        else:
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
            commit_yaml = await fetch_commit_yaml_from_provider(
                commit, repository_service
            )
            save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        except InvalidYamlException as ex:
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
        )

    def schedule_task(self, commit, commit_yaml, argument_list):
        commit_yaml = commit_yaml.to_dict()
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
                    ),
                )
                chain_to_call.append(sig)
        if chain_to_call:
            finish_sig = upload_finisher_task.signature(
                kwargs=dict(
                    repoid=commit.repoid,
                    commitid=commit.commitid,
                    commit_yaml=commit_yaml,
                ),
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
            try:
                hook_result = await create_webhook_on_provider(repository_service)
                hookid = hook_result["id"]
                log.info("Registered hook %s for repo %s", hookid, repository.repoid)
                repository.hookid = hookid
                repo_data["repo"]["hookid"] = hookid
                return True
            except TorngitClientError:
                log.warning(
                    "Failed to create project webhook",
                    extra=dict(repoid=repository.repoid, commit=commit.commitid),
                )
        return False

    async def possibly_update_commit_from_provider_info(
        self, commit, repository_service
    ):
        repoid = commit.repoid
        commitid = commit.commitid
        try:
            if not commit.message:
                log.info(
                    "Commit does not have all needed info. Reaching provider to fetch info",
                    extra=dict(repoid=repoid, commit=commitid),
                )
                await update_commit_from_provider_info(repository_service, commit)
                return True
        except TorngitObjectNotFoundError:
            log.warning(
                "Could not update commit with info because it was not found at the provider",
                extra=dict(repoid=repoid, commit=commitid),
            )
            return False
        log.debug(
            "Not updating commit because it already seems to be populated",
            extra=dict(repoid=repoid, commit=commitid),
        )
        return False

    def normalize_upload_arguments(
        self, commit: Commit, arguments: Mapping[str, Any], redis_connection: Redis
    ):
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
            content = download_archive_from_redis(redis_connection, redis_key)
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


RegisteredUploadTask = celery_app.register_task(UploadTask())
upload_task = celery_app.tasks[RegisteredUploadTask.name]
