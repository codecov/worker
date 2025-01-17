import logging
import re
from enum import Enum
from functools import partial
from typing import Optional, TypedDict

from celery.exceptions import MaxRetriesExceededError
from shared.celery_config import (
    compute_comparison_task_name,
    notification_orchestrator_task_name,
    notify_task_name,
    pulls_task_name,
)
from shared.torngit.exceptions import TorngitClientError, TorngitServerFailureError
from shared.yaml import UserYaml
from sqlalchemy.orm.session import Session

from app import celery_app
from celery_config import notify_error_task_name
from database.enums import CommitErrorTypes, ReportType
from database.models import Commit, Pull
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.clock import get_seconds_to_next_hour
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.save_commit_error import save_commit_error
from services.comparison import (
    get_or_create_comparison,
)
from services.lock_manager import LockManager, LockRetry, LockType
from services.processing.state import ProcessingState, should_trigger_postprocessing
from services.processing.types import ProcessingResult
from services.redis import Redis, get_redis_connection
from services.report import ReportService
from services.repository import (
    get_repo_provider_service,
)
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME

log = logging.getLogger(__name__)
regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]")


class ShouldCallNotifyResult(Enum):
    NOTIFY = "notify"
    NOTIFY_ERROR = "notify_error"
    DO_NOT_NOTIFY = "do_not_notify"
    WAIT_TO_NOTIFY = "wait_to_notify"


class ShouldCallNotifyResponse(TypedDict):
    notification_result: ShouldCallNotifyResult
    reason: str
    # This is currently not used, but my idea here was to provide it and log this message in switch statements.
    # Logging could become a bit less flexible but there's less logging altogether. Thoughts?
    message: str


# TODO: Ask: does this need a throws = (SoftTimeLimitExceeded,)?
class NotificationOrchestratorTask(
    BaseCodecovTask, name=notification_orchestrator_task_name
):
    def run_impl(
        self,
        db_session: Session,
        *args,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        processing_results: list[ProcessingResult],
        report_code: str | None = None,
        empty_upload=None,
        **kwargs,
    ):
        lock_manager = LockManager(
            repoid=repoid,
            commitid=commitid,
            # Currently hardcoded to coverage, should be variable to the report type
            report_type=ReportType.COVERAGE,
            # TODO: Ask if we need a specific timeout hard timeout for this task, unsure
            lock_timeout=max(80, self.hard_time_limit_task),
        )
        try:
            lock_acquired = False
            with lock_manager.locked(
                lock_type=LockType.NOTIFICATION_ORCHESTRATOR,
                retry_num=self.request.retries,
            ):
                lock_acquired = True
                return self.run_impl_within_lock(
                    db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    processing_results=processing_results,
                    report_code=report_code,
                    empty_upload=empty_upload,
                    **kwargs,
                )
        # TODO: What should happen when there's a lock error? I think this should change to some retrying mechanism
        # Should it be a LockRetry or a LockError?
        except LockRetry as err:
            (
                log.info(
                    "Not notifying because there is another notification already happening",
                    extra=dict(
                        repoid=repoid,
                        commitid=commitid,
                        error_type=type(err),
                        lock_acquired=lock_acquired,
                    ),
                ),
            )
            UploadFlow.log(UploadFlow.NOTIF_LOCK_ERROR)
            return {
                "notified": False,
                "notifications": None,
                "reason": "unobtainable_lock",
            }

    def run_impl_within_lock(
        self,
        db_session: Session,
        *args,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        processing_results: list[ProcessingResult],
        report_code: str | None = None,
        empty_upload=None,
        **kwargs,
    ):
        repoid = int(repoid)
        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database."
        commit_yaml = UserYaml(commit_yaml)

        log_extra_dict = {
            "repoid": commit.repoid,
            "commit": commit.commitid,
            "commit_yaml": commit_yaml.to_dict(),
            "processing_results": processing_results,
            "report_code": report_code,
            "parent_task": self.request.parent_id,
        }

        # Main logic that controls the notification states and decides what to do based on them
        should_call_notification = self.should_call_notifications(
            commit=commit,
            commit_yaml=commit_yaml,
            processing_results=processing_results,
            report_code=report_code,
            log_extra_dict=log_extra_dict,
        )
        match should_call_notification:
            case {"notification_result": ShouldCallNotifyResult.NOTIFY}:
                notify_kwargs = {
                    "repoid": repoid,
                    "commitid": commitid,
                    "current_yaml": commit_yaml.to_dict(),
                    "empty_upload": empty_upload,
                }
                notify_kwargs = UploadFlow.save_to_kwargs(notify_kwargs)
                task = self.app.tasks[notify_task_name].apply_async(
                    kwargs=notify_kwargs
                )
                log.info(
                    "Scheduling notify task",
                    extra={
                        **log_extra_dict,
                        "notify_task_id": task.id,
                    },
                )
                self.orchestrator_side_effects(db_session=db_session, commit=commit)
                # TODO: We should add a UploadFlow.ATTEMPTING_NOTIFICATION
            case {
                "notification_result": ShouldCallNotifyResult.DO_NOT_NOTIFY,
                "reason": reason,
            }:
                log.info(
                    "Skipping notify task", extra={**log_extra_dict, "reason": reason}
                )
                UploadFlow.log(UploadFlow.SKIPPING_NOTIFICATION)
            case {
                "notification_result": ShouldCallNotifyResult.WAIT_TO_NOTIFY,
                "reason": reason,
                "extra": {"max_retries": max_retries, "countdown": countdown},
            }:
                log.info(
                    "Unable to start notifications. Retrying again later.",
                    extra={
                        **log_extra_dict,
                        "reason": reason,
                        "countdown": countdown,
                        "max_retries": max_retries,
                    },
                )
                return self._attempt_retry(
                    max_retries=max_retries,
                    countdown=countdown,
                    log_extra_dict=log_extra_dict,
                )
            case {"notification_result": ShouldCallNotifyResult.NOTIFY_ERROR}:
                log.info("Attempting to notify error", extra=log_extra_dict)
                notify_error_kwargs = {
                    "repoid": repoid,
                    "commitid": commitid,
                    "current_yaml": commit_yaml.to_dict(),
                }
                notify_error_kwargs = UploadFlow.save_to_kwargs(notify_error_kwargs)
                task = self.app.tasks[notify_error_task_name].apply_async(
                    kwargs=notify_error_kwargs
                )

        return should_call_notification

    def should_call_notifications(
        self,
        commit: Commit,
        commit_yaml: UserYaml,
        processing_results: list[ProcessingResult],
        log_extra_dict: dict,
        report_code: str | None = None,
    ) -> ShouldCallNotifyResponse:
        # Defines all the logic to consider a notification
        should_notify_check_functions = [
            partial(
                self.upload_processing_checks, processing_results=processing_results
            ),
            partial(
                self.yaml_checks,
                processing_results=processing_results,
                commit_yaml=commit_yaml,
            ),
            partial(self.business_logic_checks, report_code=report_code),
        ]

        # Loop through all the notification checks. Each function should return None unless
        # it shouldn't notify, error or it needs to retry
        for func in should_notify_check_functions:
            result = func(commit=commit, log_extra_dict=log_extra_dict)
            if result:
                return result

        return ShouldCallNotifyResponse(
            notification_result=ShouldCallNotifyResult.NOTIFY,
            reason="successful_notification_scheduling",
            message="Scheduling notify task",
        )

    def upload_processing_checks(
        self,
        commit: Commit,
        processing_results: list[ProcessingResult],
        log_extra_dict: dict,
    ) -> Optional[ShouldCallNotifyResponse]:
        # Checks if there is at least a success
        processing_successes = [x["successful"] for x in processing_results]
        if not any(processing_successes):
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="no_successful_processing",
                message="No successful processing",
            )

        # Determine if there should be anything post_processing
        repoid = commit.repoid
        commitid = commit.commitid
        state = ProcessingState(repoid, commitid)
        if not should_trigger_postprocessing(state.get_upload_numbers()):
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="no_postprocessing_needed",
                message="No need to trigger postprocessing",
            )

        # Determines if there are other uploads processing or incoming
        redis_connection = get_redis_connection()
        if self.has_upcoming_notifies_according_to_redis(
            redis_connection, repoid, commitid
        ):
            log.info(
                "Not notifying because there are seemingly other jobs being processed yet",
                extra=log_extra_dict,
            )
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="has_other_notifications_coming",
                message="Not notifying because there are seemingly other jobs being processed yet",
            )

        return None

    def yaml_checks(
        self,
        commit: Commit,
        processing_results: list[ProcessingResult],
        commit_yaml: UserYaml,
        log_extra_dict: dict,
    ) -> Optional[ShouldCallNotifyResponse]:
        # Checks for manual trigger
        manual_trigger = read_yaml_field(
            commit_yaml, ("codecov", "notify", "manual_trigger")
        )
        if manual_trigger:
            log.info(
                "Not scheduling notify because manual trigger is used",
                extra=log_extra_dict,
            )
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="has_manual_trigger_yaml_setting",
                message="Not scheduling notify because manual trigger is used",
            )

        # Checks for after_n_builds
        after_n_builds = (
            read_yaml_field(commit_yaml, ("codecov", "notify", "after_n_builds")) or 0
        )
        if after_n_builds > 0:
            report = ReportService(commit_yaml).get_existing_report_for_commit(commit)
            number_sessions = len(report.sessions) if report is not None else 0
            if after_n_builds > number_sessions:
                log.info(
                    f"Not scheduling notify because `after_n_builds` is {after_n_builds} and we only found {number_sessions} builds",
                    extra=log_extra_dict,
                )
                return {
                    "notification_result": ShouldCallNotifyResult.DO_NOT_NOTIFY,
                    "reason": "has_after_n_builds_yaml_setting",
                    "message": f"Not scheduling notify because `after_n_builds` is {after_n_builds} and we only found {number_sessions} builds",
                }

        # Checks for notify_error
        notify_error = read_yaml_field(
            commit_yaml,
            ("codecov", "notify", "notify_error"),
            _else=False,
        )
        processing_successes = [x["successful"] for x in processing_results]
        if notify_error and (
            len(processing_successes) == 0 or not all(processing_successes)
        ):
            log.info(
                "Not scheduling notify because there is a non-successful processing result",
                extra=log_extra_dict,
            )
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.NOTIFY_ERROR,
                reason="has_notify_error_yaml_setting",
                message="Not scheduling notify because there is a non-successful processing result",
            )

        # Creates repository_service and ci_results to use with yaml settings
        try:
            installation_name_to_use = get_installation_name_for_owner_for_task(
                self.name, commit.repository.owner
            )
            # This is technically a different repository_service method than the one used in the notify task. I
            # replaced it because the other method is a) deeply intertwined with the notify file and b) it seems
            # to be extra specific just for the notification aspect of it, so this should suffice for other checks.
            # Please look corroborate this isn't a red flag.
            repository_service = get_repo_provider_service(commit.repository)
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value
            )
            log.warning(
                "Unable to start notifications because repo doesn't have a valid bot",
                extra=log_extra_dict,
            )
            UploadFlow.log(UploadFlow.NOTIF_NO_VALID_INTEGRATION)
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="has_no_valid_bot",
                message="Unable to start notifications because repo doesn't have a valid bot",
            )
        except NoConfiguredAppsAvailable as exp:
            if exp.rate_limited_count > 0:
                # There's at least 1 app that we can use to communicate with GitHub,
                # but this app happens to be rate limited now. We try again later.
                # Min wait time of 1 minute
                retry_delay_seconds = max(60, get_seconds_to_next_hour())
                log.warning(
                    "Unable to start notifications. Retrying again later.",
                    extra={
                        **log_extra_dict,
                        "apps_available": exp.apps_count,
                        "apps_rate_limited": exp.rate_limited_count,
                        "apps_suspended": exp.suspended_count,
                        "countdown_seconds": retry_delay_seconds,
                    },
                )
                return ShouldCallNotifyResponse(
                    notification_result=ShouldCallNotifyResult.WAIT_TO_NOTIFY,
                    reason="retrying_because_app_is_rate_limited",
                    message="Unable to start notifications. Retrying again later.",
                    extra=dict(
                        max_retries=10,
                        countdown=retry_delay_seconds,
                    ),
                )
            # Maybe we have apps that are suspended. We can't communicate with github.
            log.warning(
                "We can't find an app to communicate with GitHub. Not notifying.",
                extra={
                    **log_extra_dict,
                    "apps_available": exp.apps_count,
                    "apps_suspended": exp.suspended_count,
                },
            )
            UploadFlow.log(UploadFlow.NOTIF_NO_APP_INSTALLATION)
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="no_valid_github_app_found",
                message="We can't find an app to communicate with GitHub. Not notifying.",
            )

        try:
            ci_results = self.fetch_and_update_whether_ci_passed(
                repository_service, commit, commit_yaml
            )
        except TorngitClientError as ex:
            log.info(
                "Unable to fetch CI results due to a client problem. Not notifying user",
                extra={
                    **log_extra_dict,
                    "code": ex.code,
                },
            )
            UploadFlow.log(UploadFlow.NOTIF_GIT_CLIENT_ERROR)
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="not_able_fetch_ci_result",
                message="Unable to fetch CI results due to a client problem. Not notifying user",
            )
        except TorngitServerFailureError:
            log.info(
                "Unable to fetch CI results due to server issues. Not notifying user",
                extra=log_extra_dict,
            )
            UploadFlow.log(UploadFlow.NOTIF_GIT_SERVICE_ERROR)
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="server_issues_ci_result",
                message="Unable to fetch CI results due to a client problem. Not notifying user",
            )

        # Check for wait_for_ci based on the CI results and reattempt if true
        wait_for_ci = read_yaml_field(
            commit_yaml, ("codecov", "notify", "wait_for_ci"), True
        )
        if wait_for_ci and ci_results is None:
            log.info(
                "Not sending notifications yet because we are waiting for CI to finish. Attempting retry",
                extra=log_extra_dict,
            )
            ghapp_default_installations = list(
                filter(
                    lambda obj: obj.name == installation_name_to_use
                    and obj.is_configured(),
                    commit.repository.owner.github_app_installations or [],
                )
            )
            rely_on_webhook_ghapp = ghapp_default_installations != [] and any(
                obj.is_repo_covered_by_integration(commit.repository)
                for obj in ghapp_default_installations
            )
            rely_on_webhook_legacy = commit.repository.using_integration
            if (
                rely_on_webhook_ghapp
                or rely_on_webhook_legacy
                or commit.repository.hookid
            ):
                # rely on the webhook, but still retry in case we miss the webhook
                max_retries = 5
                countdown = (60 * 3) * 2**self.request.retries
            else:
                max_retries = 10
                countdown = 15 * 2**self.request.retries
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.WAIT_TO_NOTIFY,
                reason="retrying_because_wait_for_ci",
                message="Not sending notifications yet because we are waiting for CI to finish. Attempting retry",
                extra=dict(
                    max_retries=max_retries,
                    countdown=countdown,
                ),
            )

        # Check for require_ci_to_pass if ci_results is false
        require_ci_to_pass = read_yaml_field(
            commit_yaml, ("codecov", "require_ci_to_pass"), True
        )
        if require_ci_to_pass and ci_results is False:
            log.info(
                "Not sending notifications because CI failed", extra=log_extra_dict
            )
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.NOTIFY_ERROR,
                reason="has_require_ci_to_pass_yaml_setting_and_no_ci_results",
                message="Not sending notifications because CI failed",
            )
        return None

    def business_logic_checks(
        self, commit: Commit, log_extra_dict: dict, report_code: str | None = None
    ):
        # Notifications should be off in case of local uploads, and report code wouldn't be null in that case
        if report_code is not None:
            log.info(
                "Not scheduling notify because it's a local upload",
                extra=log_extra_dict,
            )
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="has_require_ci_to_pass_yaml_setting_and_no_ci_results",
                message="Not scheduling notify because it's a local upload",
            )

        # Some check on CI skipping from some regex? Idk what this is
        if regexp_ci_skip.search(commit.message or ""):
            commit.state = "skipped"
            log.info(
                "Not scheduling notify because regex wants to skip ci",
                extra=log_extra_dict,
            )
            return ShouldCallNotifyResponse(
                notification_result=ShouldCallNotifyResult.DO_NOT_NOTIFY,
                reason="has_has_regexp_ci_skip",
                message="Not scheduling notify because regex wants to skip ci",
            )
        return None

    def orchestrator_side_effects(
        self,
        db_session: Session,
        commit: Commit,
    ):
        if commit.pullid:
            repoid = commit.repoid
            pull = (
                db_session.query(Pull)
                .filter_by(repoid=repoid, pullid=commit.pullid)
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
                        self.app.tasks[compute_comparison_task_name].apply_async(
                            kwargs=dict(comparison_id=comparison.id)
                        )

    def _attempt_retry(
        self, max_retries: int, countdown: int, log_extra_dict: dict
    ) -> None:
        try:
            self.retry(max_retries=max_retries, countdown=countdown)
        except MaxRetriesExceededError:
            log.warning(
                "Not attempting to retry notifications since we already retried too many times",
                extra={
                    **log_extra_dict,
                    "max_retries": max_retries,
                    "next_countdown_would_be": countdown,
                },
            )
            UploadFlow.log(UploadFlow.NOTIF_TOO_MANY_RETRIES)
            return {
                "notification_result": ShouldCallNotifyResult.DO_NOT_NOTIFY,
                "reason": "too_many_retries",
                "message": "Not attempting to retry notifications since we already retried too many times",
            }

    def has_upcoming_notifies_according_to_redis(
        self, redis_connection: Redis, repoid: int, commitid: str
    ) -> bool:
        """Checks whether there are any jobs processing according to Redis right now and,
            therefore, whether more up-to-date notifications will come after this anyway

            It's very important to have this code be conservative against saying
                there are upcoming notifies already. The point of this code is to
                avoid extra notifications for efficiency purposes, but it is better
                to send extra notifications than to lack notifications

        Args:
            redis_connection (Redis): The redis connection we check against
            repoid (int): The repoid of the commit
            commitid (str): The commitid of the commit
        """
        upload_processing_lock_name = UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid)
        if redis_connection.get(upload_processing_lock_name):
            return True
        return False


RegisteredNotificationOrchestratorTask = celery_app.register_task(
    NotificationOrchestratorTask()
)
notification_orchestrator_task = celery_app.tasks[
    RegisteredNotificationOrchestratorTask.name
]
