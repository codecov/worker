import itertools
import logging
import time
import uuid
from copy import deepcopy
from typing import Dict, Optional

import orjson
import sentry_sdk
from asgiref.sync import async_to_sync
from celery import chain, chord
from django.db import transaction as django_transaction
from django.utils import timezone
from redis import Redis
from redis.exceptions import LockError
from shared.celery_config import upload_task_name
from shared.config import get_config
from shared.django_apps.user_measurements.models import UserMeasurement
from shared.metrics import Histogram
from shared.torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError
from shared.upload.utils import UploaderType, bulk_insert_coverage_measurements
from shared.yaml import UserYaml
from shared.yaml.user_yaml import OwnerContext
from sqlalchemy.orm import Session

from app import celery_app
from database.enums import CommitErrorTypes, ReportType
from database.models import Commit, CommitReport, RepositoryFlag
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from helpers.checkpoint_logger.flows import TestResultsFlow, UploadFlow
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.save_commit_error import save_commit_error
from services.archive import ArchiveService
from services.bundle_analysis.report import BundleAnalysisReportService
from services.processing.state import ProcessingState
from services.processing.types import UploadArguments
from services.redis import download_archive_from_redis, get_redis_connection
from services.report import (
    BaseReportService,
    NotReadyToBuildReportYetError,
    ReportService,
)
from services.repository import (
    create_webhook_on_provider,
    fetch_commit_yaml_and_possibly_store,
    get_repo_provider_service,
    gitlab_webhook_update,
    possibly_update_commit_from_provider_info,
)
from services.test_results import TestResultsReportService
from tasks.base import BaseCodecovTask
from tasks.bundle_analysis_notify import bundle_analysis_notify_task
from tasks.bundle_analysis_processor import bundle_analysis_processor_task
from tasks.test_results_finisher import test_results_finisher_task
from tasks.test_results_processor import test_results_processor_task
from tasks.upload_finisher import upload_finisher_task
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME, upload_processor_task

log = logging.getLogger(__name__)

CHUNK_SIZE = 3

UPLOADS_PER_TASK_SCHEDULE = Histogram(
    "worker_uploads_per_schedule",
    "The number of individual uploads scheduled for processing",
    ["report_type"],
    buckets=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50],
)


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
        report_code: str | None = None,
        redis_connection: Redis | None = None,
    ):
        self.repoid = repoid
        self.commitid = commitid
        self.report_type = report_type
        self.report_code = report_code
        self.redis_connection = redis_connection or get_redis_connection()

    def log_extra(self, **kwargs) -> dict:
        return dict(
            report_type=self.report_type.value,
            report_code=self.report_code,
            **kwargs,
        )

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
        return bool(self.redis_connection.get(lock_name))

    def is_currently_processing(self) -> bool:
        return self.is_locked("upload_processing")

    def has_pending_jobs(self) -> bool:
        return bool(self.redis_connection.exists(self.upload_location))

    def last_upload_timestamp(self):
        if self.report_type == ReportType.COVERAGE:
            # for backward compat this does not include the report type
            redis_key = f"latest_upload/{self.repoid}/{self.commitid}"
        else:
            redis_key = (
                f"latest_upload/{self.repoid}/{self.commitid}/{self.report_type.value}"
            )
        return self.redis_connection.get(redis_key)

    def kwargs_for_retry(self, kwargs: dict) -> dict:
        return dict(
            **kwargs,
            repoid=self.repoid,
            commitid=self.commitid,
            report_type=self.report_type.value,
            report_code=self.report_code,
        )

    def arguments_list(self):
        """
        Retrieves a list of arguments from redis, parses them
        and feeds them to the processing code.

        This function doesn't go infinite because it keeps emptying the respective key on redis.
        It will only go arbitrarily long if someone else keeps uploading more and more arguments
        to such list

        Yields:
            dict: A dict with the parameters to be passed
        """
        uploads_list_key = self.upload_location
        log.debug("Fetching arguments from redis %s", uploads_list_key)
        while arguments := self.redis_connection.lpop(uploads_list_key, count=50):
            for arg in arguments:
                yield orjson.loads(arg)

    def normalize_arguments(self, commit: Commit, arguments: UploadArguments):
        """
        Normalizes and validates the argument list from the user.

        Does things like:

            - replacing a redis-stored value with a storage one (by doing an upload)
            - Removing unnecessary sensitive information for the arguments
        """
        commit_sha = commit.commitid
        reportid = arguments.get("reportid")
        if redis_key := arguments.pop("redis_key", None):
            archive_service = ArchiveService(commit.repository)
            content = download_archive_from_redis(self.redis_connection, redis_key)
            written_path = archive_service.write_raw_upload(
                commit_sha, reportid, content
            )
            log.info(
                "Writing report content from redis to storage",
                extra=dict(path=written_path),
            )
            arguments["url"] = written_path
        arguments.pop("token", None)

        flags: list | str | None = arguments.get("flags")
        if not flags:
            flags = []
        elif isinstance(flags, str):
            flags = [flag.strip() for flag in flags.split(",")]
        arguments["flags"] = flags

        return arguments


def _should_debounce_processing(upload_context: UploadContext) -> Optional[float]:
    """
    Queries the `UploadContext`s `last_upload_timestamp` and determines if
    another upload should be debounced by some time.
    """
    upload_processing_delay = get_config("setup", "upload_processing_delay")
    if upload_processing_delay is None:
        return None

    upload_processing_delay = float(upload_processing_delay)
    last_upload_timestamp = upload_context.last_upload_timestamp()
    if last_upload_timestamp is None:
        return None

    last_upload_delta = time.time() - float(last_upload_timestamp)
    if last_upload_delta < upload_processing_delay:
        return max(30, upload_processing_delay - last_upload_delta)
    return None


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

    def run_impl(
        self,
        db_session: Session,
        repoid: int,
        commitid: str,
        report_type: str = "coverage",
        report_code: str | None = None,
        *args,
        **kwargs,
    ):
        upload_context = UploadContext(
            repoid=int(repoid),
            commitid=commitid,
            report_type=ReportType(report_type),
            report_code=report_code,
        )
        if report_code:
            sentry_sdk.capture_message(
                "Customer is using non-default `report_code`",
                tags={"report_type": report_type, "report_code": report_code},
            )

        # If we're a retry, kwargs will already have our first checkpoint.
        # If not, log it directly into kwargs so we can pass it onto other tasks
        if upload_context.report_type == ReportType.COVERAGE:
            UploadFlow.log(
                UploadFlow.UPLOAD_TASK_BEGIN, kwargs=kwargs, ignore_repeat=True
            )
        elif upload_context.report_type == ReportType.TEST_RESULTS:
            TestResultsFlow.log(
                TestResultsFlow.TEST_RESULTS_BEGIN, kwargs=kwargs, ignore_repeat=True
            )

        log.info("Received upload task", extra=upload_context.log_extra())

        if not upload_context.has_pending_jobs():
            log.info("No pending jobs. Upload task is done.")
            self.maybe_log_upload_checkpoint(UploadFlow.NO_PENDING_JOBS)
            return {
                "was_setup": False,
                "was_updated": False,
                "tasks_were_scheduled": False,
            }

        if upload_context.is_currently_processing() and self.request.retries == 0:
            log.info(
                "Currently processing upload. Retrying in 60s.",
                extra=upload_context.log_extra(),
            )
            self.retry(countdown=60, kwargs=upload_context.kwargs_for_retry(kwargs))

        if retry_countdown := _should_debounce_processing(upload_context):
            log.info(
                "Retrying due to very recent uploads.",
                extra=upload_context.log_extra(
                    countdown=retry_countdown,
                ),
            )
            self.retry(
                countdown=retry_countdown,
                kwargs=upload_context.kwargs_for_retry(kwargs),
            )

        lock_name = upload_context.lock_name("upload")
        try:
            with upload_context.redis_connection.lock(
                lock_name,
                timeout=max(300, self.hard_time_limit_task),
                blocking_timeout=5,
            ):
                # Check whether a different `Upload` task has "stolen" our uploads
                if not upload_context.has_pending_jobs():
                    log.info("No pending jobs. Upload task is done.")
                    self.maybe_log_upload_checkpoint(UploadFlow.NO_PENDING_JOBS)
                    return {
                        "was_setup": False,
                        "was_updated": False,
                        "tasks_were_scheduled": False,
                    }

                return self.run_impl_within_lock(
                    db_session,
                    upload_context,
                    kwargs,
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
                    extra=upload_context.log_extra(),
                )
                self.maybe_log_upload_checkpoint(UploadFlow.NO_PENDING_JOBS)
                return {
                    "was_setup": False,
                    "was_updated": False,
                    "tasks_were_scheduled": False,
                }
            if self.request.retries > 1:
                log.info(
                    "Not retrying since we already had too many retries",
                    extra=upload_context.log_extra(),
                )
                self.maybe_log_upload_checkpoint(UploadFlow.TOO_MANY_RETRIES)
                return {
                    "was_setup": False,
                    "was_updated": False,
                    "tasks_were_scheduled": False,
                    "reason": "too_many_retries",
                }
            retry_countdown = 20 * 2**self.request.retries
            log.warning(
                "Retrying upload",
                extra=upload_context.log_extra(countdown=retry_countdown),
            )
            self.retry(
                max_retries=3,
                countdown=retry_countdown,
                kwargs=upload_context.kwargs_for_retry(kwargs),
            )

    @sentry_sdk.trace
    def run_impl_within_lock(
        self,
        db_session: Session,
        upload_context: UploadContext,
        kwargs: dict,
    ):
        log.info("Starting processing of report", extra=upload_context.log_extra())
        repoid = upload_context.repoid
        report_type = upload_context.report_type

        if report_type == ReportType.COVERAGE:
            try:
                UploadFlow.log(UploadFlow.PROCESSING_BEGIN)
            except ValueError as e:
                log.warning(
                    "CheckpointLogger failed to log/submit", extra=dict(error=e)
                )

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == upload_context.commitid)
            .first()
        )
        assert commit, "Commit not found in database."
        repository = commit.repository
        repository_service = None

        was_updated, was_setup = False, False
        try:
            installation_name_to_use = get_installation_name_for_owner_for_task(
                self.name, repository.owner
            )
            repository_service = get_repo_provider_service(
                repository, installation_name_to_use=installation_name_to_use
            )
            was_updated = possibly_update_commit_from_provider_info(
                commit, repository_service
            )
            was_setup = self.possibly_setup_webhooks(commit, repository_service)
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit,
                error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
                error_params=dict(repoid=repoid, repository_service=repository_service),
            )

            log.warning(
                "Unable to reach git provider because repo doesn't have a valid bot",
                extra=upload_context.log_extra(),
            )
        except TorngitRepoNotFoundError:
            log.warning(
                "Unable to reach git provider because this specific bot/integration can't see that repository",
                extra=upload_context.log_extra(),
            )
        except TorngitClientError:
            log.warning(
                "Unable to reach git provider because there was a 4xx error",
                extra=upload_context.log_extra(),
                exc_info=True,
            )

        if repository_service:
            commit_yaml = fetch_commit_yaml_and_possibly_store(
                commit, repository_service
            )
        else:
            context = OwnerContext(
                owner_onboarding_date=repository.owner.createstamp,
                owner_plan=repository.owner.plan,
                ownerid=repository.ownerid,
            )
            commit_yaml = UserYaml.get_final_yaml(
                owner_yaml=repository.owner.yaml,
                repo_yaml=repository.yaml,
                commit_yaml=None,
                owner_context=context,
            )

        report_service: BaseReportService
        if report_type == ReportType.COVERAGE:
            # TODO: consider renaming class to `CoverageReportService`
            report_service = ReportService(
                commit_yaml, gh_app_installation_name=installation_name_to_use
            )
        elif report_type == ReportType.BUNDLE_ANALYSIS:
            report_service = BundleAnalysisReportService(commit_yaml)
        elif report_type == ReportType.TEST_RESULTS:
            report_service = TestResultsReportService(commit_yaml)
        else:
            raise NotImplementedError(f"no report service for: {report_type.value}")

        try:
            log.info("Initializing and saving report", extra=upload_context.log_extra())
            commit_report = report_service.initialize_and_save_report(
                commit, upload_context.report_code
            )
        except NotReadyToBuildReportYetError:
            log.warning(
                "Commit not yet ready to build its initial report. Retrying in 60s.",
                extra=upload_context.log_extra(),
            )
            self.retry(countdown=60, kwargs=upload_context.kwargs_for_retry(kwargs))

        argument_list: list[UploadArguments] = []

        # Measurements insertion performance
        measurements = []
        created_at = timezone.now()

        # Bulk fetch or create flags
        all_flags_in_uploads = self._bulk_fetch_or_create_all_uploads_flags(
            db_session=db_session, upload_context=upload_context, repoid=repoid
        )

        for arguments in upload_context.arguments_list():
            arguments = upload_context.normalize_arguments(commit, arguments)
            if "upload_id" not in arguments:
                upload = report_service.create_report_upload(arguments, commit_report)
                arguments["upload_id"] = upload.id_
                # Attach flags to the upload, later to be committed
                flag_names = arguments["flags"]
                upload.flags = [all_flags_in_uploads.get(name) for name in flag_names]
                # Adding measurements to array to later add in bulk
                measurements.append(
                    UserMeasurement(
                        owner_id=repository.owner.ownerid,
                        repo_id=repository.repoid,
                        commit_id=commit.id,
                        upload_id=upload.id,
                        # CLI precreates the upload in API so this defaults to Legacy
                        uploader_used=UploaderType.LEGACY.value,
                        private_repo=repository.private,
                        report_type=commit_report.report_type,
                        created_at=created_at,
                    )
                )

            # TODO(swatinem): eventually migrate from `upload_pk` to `upload_id`:
            arguments["upload_pk"] = arguments["upload_id"]
            argument_list.append(arguments)

        # Bulk insert coverage measurements
        if measurements:
            self._bulk_insert_coverage_measurements(measurements=measurements)

        if argument_list:
            db_session.commit()

            UPLOADS_PER_TASK_SCHEDULE.labels(report_type=report_type.value).observe(
                len(argument_list)
            )
            scheduled_tasks = self.schedule_task(
                commit,
                commit_yaml.to_dict(),
                argument_list,
                commit_report,
                upload_context,
            )

            log.info(
                f"Scheduling {upload_context.report_type.value} processing tasks",
                extra=upload_context.log_extra(
                    argument_list=argument_list,
                    number_arguments=len(argument_list),
                    scheduled_task_ids=scheduled_tasks.as_tuple(),
                ),
            )

        else:
            self.maybe_log_upload_checkpoint(UploadFlow.INITIAL_PROCESSING_COMPLETE)
            self.maybe_log_upload_checkpoint(UploadFlow.NO_REPORTS_FOUND)
            log.info(
                "Not scheduling task because there were no arguments found on redis",
                extra=upload_context.log_extra(),
            )
        return {"was_setup": was_setup, "was_updated": was_updated}

    def _bulk_insert_coverage_measurements(self, measurements: list[UserMeasurement]):
        bulk_insert_coverage_measurements(measurements=measurements)
        django_transaction.commit()

    def _bulk_fetch_or_create_all_uploads_flags(
        self, db_session: Session, upload_context: UploadContext, repoid: int
    ) -> Dict[str, RepositoryFlag] | dict:
        """
        This function bulk fetches and bulk creates missing RepositoryFlag records
        and returns a dictionary with flag names and their RepositoryFlag object
        to be attached with their respective uploads
        """
        # Bulk query existing flags from DB
        all_flag_names = set()
        for arguments in upload_context.arguments_list():
            if argument_flags := arguments.get("flags"):
                all_flag_names.update(argument_flags)

        if not all_flag_names:
            return {}
        existing_flags = (
            db_session.query(RepositoryFlag)
            .filter(
                RepositoryFlag.repository_id == repoid,
                RepositoryFlag.flag_name.in_(all_flag_names),
            )
            .all()
        )
        # Handy helper flags dict
        existing_flags_dict = {flag.flag_name: flag for flag in existing_flags}

        # Bulk add missing flags to DB
        missing_flag_names = all_flag_names - set(existing_flags_dict.keys())
        missing_flags = [
            RepositoryFlag(repository_id=repoid, flag_name=name)
            for name in missing_flag_names
        ]

        if missing_flags:
            db_session.bulk_save_objects(missing_flags)
            db_session.commit()

            for flag in missing_flags:
                existing_flags_dict[flag.flag_name] = flag

        return existing_flags_dict

    def schedule_task(
        self,
        commit: Commit,
        commit_yaml: dict,
        argument_list: list[UploadArguments],
        commit_report: CommitReport,
        upload_context: UploadContext,
    ):
        # Carryforward the parent BA report for the current commit's BA report when handling uploads
        # that's not bundle analysis type.
        self.possibly_carryforward_bundle_report(
            commit, commit_report, commit_yaml, argument_list
        )

        if upload_context.report_type == ReportType.COVERAGE:
            assert (
                commit_report.report_type is None
                or commit_report.report_type == ReportType.COVERAGE.value
            )
            return self._schedule_coverage_processing_task(
                commit,
                commit_yaml,
                argument_list,
                commit_report,
            )
        elif upload_context.report_type == ReportType.BUNDLE_ANALYSIS:
            assert commit_report.report_type == ReportType.BUNDLE_ANALYSIS.value
            return self._schedule_bundle_analysis_processing_task(
                commit,
                commit_yaml,
                argument_list,
            )
        elif upload_context.report_type == ReportType.TEST_RESULTS:
            assert commit_report.report_type == ReportType.TEST_RESULTS.value
            return self._schedule_test_results_processing_task(
                commit, commit_yaml, argument_list, commit_report
            )

    def _schedule_coverage_processing_task(
        self,
        commit: Commit,
        commit_yaml: dict,
        argument_list: list[UploadArguments],
        commit_report: CommitReport,
    ):
        self.maybe_log_upload_checkpoint(UploadFlow.INITIAL_PROCESSING_COMPLETE)

        state = ProcessingState(commit.repoid, commit.commitid)
        state.mark_uploads_as_processing(
            [int(upload["upload_id"]) for upload in argument_list]
        )

        parallel_processing_tasks = [
            upload_processor_task.s(
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml=commit_yaml,
                arguments=arguments,
            )
            for arguments in argument_list
        ]

        finisher_kwargs = {
            "repoid": commit.repoid,
            "commitid": commit.commitid,
            "commit_yaml": commit_yaml,
            "report_code": commit_report.code,
        }
        finisher_kwargs = UploadFlow.save_to_kwargs(finisher_kwargs)
        finish_parallel_sig = upload_finisher_task.signature(kwargs=finisher_kwargs)

        parallel_tasks = chord(parallel_processing_tasks, finish_parallel_sig)
        return parallel_tasks.apply_async()

    def _schedule_bundle_analysis_processing_task(
        self,
        commit: Commit,
        commit_yaml: dict,
        argument_list: list[UploadArguments],
        do_notify: Optional[bool] = True,
    ):
        task_signatures = [
            bundle_analysis_processor_task.s(
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml=commit_yaml,
                params=params,
            )
            for params in argument_list
        ]
        task_signatures[0].args = ({},)  # this is the first `previous_result`

        # it might make sense to eventually have a "finisher" task that
        # does whatever extra stuff + enqueues a notify
        if do_notify:
            task_signatures.append(
                bundle_analysis_notify_task.s(
                    repoid=commit.repoid,
                    commitid=commit.commitid,
                    commit_yaml=commit_yaml,
                )
            )

        return chain(task_signatures).apply_async()

    def _schedule_test_results_processing_task(
        self,
        commit: Commit,
        commit_yaml: dict,
        argument_list: list[UploadArguments],
        commit_report: CommitReport,
    ):
        task_group = [
            test_results_processor_task.s(
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml=commit_yaml,
                arguments_list=list(chunk),
                report_code=commit_report.code,
            )
            for chunk in itertools.batched(argument_list, CHUNK_SIZE)
        ]

        task_group[0].args = (False,)

        finisher_kwargs = {
            "repoid": commit.repoid,
            "commitid": commit.commitid,
            "commit_yaml": commit_yaml,
        }
        finisher_kwargs = TestResultsFlow.save_to_kwargs(finisher_kwargs)
        task_group.append(
            test_results_finisher_task.signature(kwargs=finisher_kwargs),
        )
        return chain(*task_group).apply_async()

    def possibly_carryforward_bundle_report(
        self,
        commit: Commit,
        commit_report: CommitReport,
        commit_yaml: dict,
        argument_list: list[UploadArguments],
    ):
        """
        If an upload is not of bundle analysis type we will create an additional BA report and upload for it.
        The reason this is done is because when doing BA comparisons if the base report does not have a proper
        BA upload then the head can not be compared. So to prevent that we will always create a BA report on
        all upload types, if the upload is not a BA upload then we will copy the parent's report to it.
        This implementation is similar to carryforward flag mechanism in coverage, note the the difference it
        that instead of traversing the commit tree during fetch, we always create a permanent report on every upload.
        """
        if (
            commit_report.report_type != ReportType.BUNDLE_ANALYSIS.value
            and commit.repository.bundle_analysis_enabled
        ):
            # Override upload_id from other upload types and create the BA uploads in the
            # BA processor task
            ba_argument_list = []
            for arg in argument_list:
                ba_arg = deepcopy(arg)
                del ba_arg["upload_id"]
                ba_arg["upload_pk"] = None
                ba_argument_list.append(ba_arg)

            self._schedule_bundle_analysis_processing_task(
                commit,
                commit_yaml,
                ba_argument_list,
                do_notify=False,
            )

    def possibly_setup_webhooks(self, commit: Commit, repository_service):
        repository = commit.repository
        repo_data = repository_service.data

        ghapp_default_installations = list(
            filter(
                lambda obj: obj.name == GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                commit.repository.owner.github_app_installations or [],
            )
        )
        should_post_ghapp = not (
            ghapp_default_installations != []
            and ghapp_default_installations[0].is_repo_covered_by_integration(
                commit.repository
            )
        )
        should_post_legacy = not repository.using_integration

        should_post_webhook = (
            should_post_legacy
            and should_post_ghapp
            and not repository.hookid
            and hasattr(repository_service, "post_webhook")
        )

        needs_webhook_secret_backfill = (
            repository_service.service in ["gitlab", "gitlab_enterprise"]
            and repository.hookid
            and not repository.webhook_secret
            and hasattr(repository_service, "edit_webhook")
        )

        # try to add webhook
        if should_post_webhook or needs_webhook_secret_backfill:
            log.info(
                "Setting or editing webhook",
                extra=dict(
                    repoid=repository.repoid,
                    commit=commit.commitid,
                    action="SET" if should_post_webhook else "EDIT",
                ),
            )
            try:
                if repository_service.service in ["gitlab", "gitlab_enterprise"]:
                    # we use per-repo webhook secrets in this case
                    webhook_secret = repository.webhook_secret or str(uuid.uuid4())
                else:
                    # service-level config value will be used instead in this case
                    webhook_secret = None

                if should_post_webhook:
                    hook_result = async_to_sync(create_webhook_on_provider)(
                        repository_service, webhook_secret=webhook_secret
                    )
                    hookid = hook_result["id"]
                    log.info(
                        "Registered hook",
                        extra=dict(
                            repoid=commit.repoid,
                            commit=commit.commitid,
                            hookid=hookid,
                            action="SET",
                        ),
                    )
                    repository.hookid = hookid
                    repo_data["repo"]["hookid"] = hookid
                    repository.webhook_secret = webhook_secret
                    return True  # was_setup
                else:
                    async_to_sync(gitlab_webhook_update)(
                        repository_service=repository_service,
                        hookid=repository.hookid,
                        secret=webhook_secret,
                    )
                    repository.webhook_secret = webhook_secret
                    log.info(
                        "Updated hook",
                        extra=dict(
                            repository_service=repository_service.service,
                            repoid=repository.repoid,
                            commit=commit.commitid,
                            hookid=repository.hookid,
                            action="EDIT",
                        ),
                    )
                    return False  # was_setup
            except TorngitClientError:
                log.warning(
                    "Failed to create or update project webhook",
                    extra=dict(
                        repoid=repository.repoid,
                        commit=commit.commitid,
                        action="SET" if should_post_webhook else "EDIT",
                    ),
                    exc_info=True,
                )
        return False

    def maybe_log_upload_checkpoint(self, checkpoint):
        if UploadFlow.has_begun():
            UploadFlow.log(checkpoint)


RegisteredUploadTask = celery_app.register_task(UploadTask())
upload_task = celery_app.tasks[RegisteredUploadTask.name]
