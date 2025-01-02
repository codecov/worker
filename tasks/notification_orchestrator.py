import logging
from typing import Optional

import sentry_sdk
import re
from asgiref.sync import async_to_sync
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
from celery_config import notify_error_task_name
from shared.bots.github_apps import (
    get_github_app_token,
    get_specific_github_app_details,
)
from shared.celery_config import (
    activate_account_user_task_name,
    new_user_activated_task_name,
    notification_orchestrator_task_name,
    status_set_error_task_name,
    compute_comparison_task_name,
    notify_task_name,
    pulls_task_name,
)
from shared.config import get_config
from shared.django_apps.codecov_auth.models import Service
from shared.reports.readonly import ReadOnlyReport
from shared.torngit.base import TokenType, TorngitBaseAdapter
from shared.torngit.exceptions import TorngitClientError, TorngitServerFailureError
from shared.typings.torngit import OwnerInfo, RepoInfo, TorngitInstanceData
from shared.yaml import UserYaml
from sqlalchemy import and_
from sqlalchemy.orm.session import Session
from enum import Enum

from app import celery_app
from database.enums import CommitErrorTypes, Decoration, NotificationState, ReportType
from database.models import Commit, Pull
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME, CompareCommit
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.clock import get_seconds_to_next_hour
from helpers.comparison import minimal_totals
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.save_commit_error import save_commit_error
from services.activation import activate_user
from services.commit_status import RepositoryCIFilter
from services.comparison import (
    ComparisonContext,
    ComparisonProxy,
    get_or_create_comparison,
)
from services.comparison.types import Comparison, FullCommit
from services.decoration import determine_decoration_details
from services.github import get_github_app_for_commit, set_github_app_for_commit
from services.lock_manager import LockManager, LockRetry, LockType
from services.notification import NotificationService
from services.redis import Redis, get_redis_connection
from services.report import ReportService
from services.processing.types import ProcessingResult
from services.processing.state import ProcessingState, should_trigger_postprocessing
from services.repository import (
    EnrichedPull,
    _get_repo_provider_service_instance,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.yaml import get_current_yaml, read_yaml_field
from tasks.base import BaseCodecovTask
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME

log = logging.getLogger(__name__)

# This should decide if it should notify based on
# Retry if someone tries to access lock and it's busy
# Processing state from other uploads with the same repo/commit id combo
# Business logic
# Notify side-effects
    # Call timeseries
    # Call pull sync task

# This needs to
# Have the same signature as the notification's task to keep notifications the same

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


regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]")

class ShouldCallNotifyResult(Enum):
    WAIT_TO_NOTIFY = "wait_to_notify"
    DO_NOT_NOTIFY = "do_not_notify"
    NOTIFY_ERROR = "notify_error"
    NOTIFY = "notify"

# TODO: Ask: does this need a throws = (SoftTimeLimitExceeded,)?
class NotificationOrchestratorTask(BaseCodecovTask, name=notification_orchestrator_task_name):
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
        print("Helllllooooooo", repoid)
        print("Helllllooooooo", commitid)
        print("Helllllooooooo", processing_results)
        print("Helllllooooooo", args)
        print("Helllllooooooo", commit_yaml)
        print("Helllllooooooo", empty_upload)
        print("Helllllooooooo", kwargs)

        lock_manager = LockManager(
            repoid=repoid,
            commitid=commitid,
            # Currently hardcoded to coverage, should be variable to the report type
            report_type=ReportType.COVERAGE,
            # Unsure if we need a specific timeout hard timeout for this task
            lock_timeout=max(80, self.hard_time_limit_task),
        )
        try:
            lock_acquired = False
            with lock_manager.locked(
                lock_type=LockType.NOTIFICATION_ORCHESTRATOR, retry_num=self.request.retries
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
            self.log_checkpoint(UploadFlow.NOTIF_LOCK_ERROR)
            return {
                "notified": False,
                "notifications": None,
                "reason": "unobtainable_lock",
            }




        # redis_connection = get_redis_connection()
        # if self.has_upcoming_notifies_according_to_redis(
        #     redis_connection, repoid, commitid
        # ):
        #     log.info(
        #         "Not notifying because there are seemingly other jobs being processed yet",
        #         extra=dict(repoid=repoid, commitid=commitid),
        #     )
        #     self.log_checkpoint(UploadFlow.SKIPPING_NOTIFICATION)
        #     return {
        #         "notified": False,
        #         "notifications": None,
        #         "reason": "has_other_notifies_coming",
        #     }


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
        # Should not notify based on yaml settings
        # Should not notify based on type of upload (empty upload)
        # Should not notify based on processing results
            # Upload states
        # Should not notify based on pending notifications
        # Should not notify based on business logic

        # States
        ### metrics log, log.info/warning. If success, side-effects
        # Should not notify
        # Should attempt to notify later
        # Should notify

        ##### Start
        redis_connection = get_redis_connection()
        repoid = int(repoid)
        commit_yaml = UserYaml(commit_yaml)

        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database."
        repository = commit.repository

        state = ProcessingState(repoid, commitid)
        processing_successes = [x["successful"] for x in processing_results]
        notifications_called = False

        extra_dict = {
            "repoid": commit.repoid,
            "commitid": commit.commitid,
            "commit_yaml": commit_yaml,
            "processing_results": processing_results,
            "report_code": report_code,
            "parent_task": self.request.parent_id,
        }

        ##### Checks other uploads and does things based on them
        # Checks if there is at least a success
        if not any(processing_successes):
            return ShouldCallNotifyResult.DO_NOT_NOTIFY

        # Determine if there should be anything post_processing
        if not should_trigger_postprocessing(state.get_upload_numbers()):
            UploadFlow.log(UploadFlow.SKIPPING_NOTIFICATION)
            return

        # Determines if there are other uploads processing or incoming
        if has_upcoming_notifies_according_to_redis(
            redis_connection, repoid, commitid
        ):
            log.info(
                "Not notifying because there are seemingly other jobs being processed yet",
                extra=dict(repoid=repoid, commitid=commitid),
            )
            self.log_checkpoint(UploadFlow.SKIPPING_NOTIFICATION)
            return {
                "notified": False,
                "notifications": None,
                "reason": "has_other_notifies_coming",
            }

        ##### Yaml settings checks
        # Checks for manual trigger
        manual_trigger = read_yaml_field(
            commit_yaml, ("codecov", "notify", "manual_trigger")
        )
        if manual_trigger:
            log.info(
                "Not scheduling notify because manual trigger is used",
                extra=extra_dict,
            )
            return ShouldCallNotifyResult.DO_NOT_NOTIFY

        # Checks for after_n_builds
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

        # Checks for notify_error
        notify_error = read_yaml_field(
            commit_yaml,
            ("codecov", "notify", "notify_error"),
            _else=False,
        )
        if notify_error and (len(processing_successes) == 0 or not all(processing_successes)):
            log.info(
                "Not scheduling notify because there is a non-successful processing result",
                extra=extra_dict,
            )
            return ShouldCallNotifyResult.NOTIFY_ERROR

        ### Checks related to repository_service and ci_results
        # ASK: this installation/bot related logic impedes notification if unavailable, but it
        # seems correct for it to be part of the notifier task, thoughts?
        try:
            installation_name_to_use = get_installation_name_for_owner_for_task(
                self.name, commit.repository.owner
            )
            # This is technically a different repository_service method than the one used in notifications. I
            # replaced it because the other method is a) deeply intertwined with the notify file and b) it seems
            # to be extra specific just for the notification aspect of it, so this should suffice for other checks.
            # Please look corroborate this isn't a red flag.
            repository_service = get_repo_provider_service(repository)
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value
            )

            log.warning(
                "Unable to start notifications because repo doesn't have a valid bot",
                extra=dict(repoid=repoid, commit=commitid),
            )
            self.log_checkpoint(UploadFlow.NOTIF_NO_VALID_INTEGRATION)
            return {"notified": False, "notifications": None, "reason": "no_valid_bot"}
        except NoConfiguredAppsAvailable as exp:
            if exp.rate_limited_count > 0:
                # There's at least 1 app that we can use to communicate with GitHub,
                # but this app happens to be rate limited now. We try again later.
                # Min wait time of 1 minute
                retry_delay_seconds = max(60, get_seconds_to_next_hour())
                log.warning(
                    "Unable to start notifications. Retrying again later.",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        apps_available=exp.apps_count,
                        apps_rate_limited=exp.rate_limited_count,
                        apps_suspended=exp.suspended_count,
                        countdown_seconds=retry_delay_seconds,
                    ),
                )
                return self._attempt_retry(
                    max_retries=10,
                    countdown=retry_delay_seconds,
                    current_yaml=commit_yaml,
                    commit=commit,
                    **kwargs,
                )
            # Maybe we have apps that are suspended. We can't communicate with github.
            log.warning(
                "We can't find an app to communicate with GitHub. Not notifying.",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    apps_available=exp.apps_count,
                    apps_suspended=exp.suspended_count,
                ),
            )
            self.log_checkpoint(UploadFlow.NOTIF_NO_APP_INSTALLATION)
            return {
                "notified": False,
                "notifications": None,
                "reason": "no_valid_github_app_found",
            }

        try:
            ci_results = self.fetch_and_update_whether_ci_passed(
                repository_service, commit, commit_yaml
            )
        except TorngitClientError as ex:
            log.info(
                "Unable to fetch CI results due to a client problem. Not notifying user",
                extra=dict(repoid=commit.repoid, commit=commit.commitid, code=ex.code),
            )
            self.log_checkpoint(UploadFlow.NOTIF_GIT_CLIENT_ERROR)
            return {
                "notified": False,
                "notifications": None,
                "reason": "not_able_fetch_ci_result",
            }
        except TorngitServerFailureError:
            log.info(
                "Unable to fetch CI results due to server issues. Not notifying user",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            self.log_checkpoint(UploadFlow.NOTIF_GIT_SERVICE_ERROR)
            return {
                "notified": False,
                "notifications": None,
                "reason": "server_issues_ci_result",
            }

        # Check for wait_for_ci based on the CI results and reattempt if true
        # should_wait_longer
        wait_for_ci = read_yaml_field(commit_yaml, ("codecov", "notify", "wait_for_ci"), True)
        if wait_for_ci and ci_results is None:
            log.info(
                "Not sending notifications yet because we are waiting for CI to finish",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
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
            return self._attempt_retry(
                max_retries=max_retries,
                countdown=countdown,
                current_yaml=commit_yaml,
                commit=commit,
                **kwargs,
            )

        # should_send_notifications require_ci_to_pass
        require_ci_to_pass = read_yaml_field(commit_yaml, ("codecov", "require_ci_to_pass"), True)
        if require_ci_to_pass and ci_results is False:
            self.app.tasks[status_set_error_task_name].apply_async(
                args=None,
                kwargs=dict(
                    repoid=commit.repoid, commitid=commit.commitid, message="CI failed."
                ),
            )
            log.info(
                "Not sending notifications because CI failed",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            return False

        ##### Business logic
        # Notifications should be off in case of local uploads, and report code wouldn't be null in that case
        if report_code is not None:
            log.info(
                "Not scheduling notify because it's a local upload",
                extra=extra_dict,
            )
            return ShouldCallNotifyResult.DO_NOT_NOTIFY

        # Some check on CI skipping from some regex? Idk what this is
        if regexp_ci_skip.search(commit.message or ""):
            commit.state = "skipped"


        # If it got here, it should notify
        notifications_called = True
        notify_kwargs = {
            "repoid": repoid,
            "commitid": commitid,
            "current_yaml": commit_yaml.to_dict(),
        }
        notify_kwargs = UploadFlow.save_to_kwargs(notify_kwargs)
        task = self.app.tasks[notify_task_name].apply_async(
            kwargs=notify_kwargs
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


        # # ASK: this installation/bot related logic impedes notification if unavailable, but it
        # # seems correct for it to be part of the notifier task, thoughts? 
        # try:
        #     installation_name_to_use = get_installation_name_for_owner_for_task(
        #         self.name, commit.repository.owner
        #     )
        #     repository_service = get_repo_provider_service_for_specific_commit(
        #         commit, installation_name_to_use
        #     )
        # except RepositoryWithoutValidBotError:
        #     save_commit_error(
        #         commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value
        #     )

        #     log.warning(
        #         "Unable to start notifications because repo doesn't have a valid bot",
        #         extra=dict(repoid=repoid, commit=commitid),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_NO_VALID_INTEGRATION)
        #     return {"notified": False, "notifications": None, "reason": "no_valid_bot"}
        # except NoConfiguredAppsAvailable as exp:
        #     if exp.rate_limited_count > 0:
        #         # There's at least 1 app that we can use to communicate with GitHub,
        #         # but this app happens to be rate limited now. We try again later.
        #         # Min wait time of 1 minute
        #         retry_delay_seconds = max(60, get_seconds_to_next_hour())
        #         log.warning(
        #             "Unable to start notifications. Retrying again later.",
        #             extra=dict(
        #                 repoid=repoid,
        #                 commit=commitid,
        #                 apps_available=exp.apps_count,
        #                 apps_rate_limited=exp.rate_limited_count,
        #                 apps_suspended=exp.suspended_count,
        #                 countdown_seconds=retry_delay_seconds,
        #             ),
        #         )
        #         return self._attempt_retry(
        #             max_retries=10,
        #             countdown=retry_delay_seconds,
        #             current_yaml=current_yaml,
        #             commit=commit,
        #             **kwargs,
        #         )
        #     # Maybe we have apps that are suspended. We can't communicate with github.
        #     log.warning(
        #         "We can't find an app to communicate with GitHub. Not notifying.",
        #         extra=dict(
        #             repoid=repoid,
        #             commit=commitid,
        #             apps_available=exp.apps_count,
        #             apps_suspended=exp.suspended_count,
        #         ),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_NO_APP_INSTALLATION)
        #     return {
        #         "notified": False,
        #         "notifications": None,
        #         "reason": "no_valid_github_app_found",
        #     }

        # if current_yaml is None:
        #     current_yaml = async_to_sync(get_current_yaml)(commit, repository_service)
        # else:
        #     current_yaml = UserYaml.from_dict(current_yaml)

        # try:
        #     ci_results = self.fetch_and_update_whether_ci_passed(
        #         repository_service, commit, current_yaml
        #     )
        # except TorngitClientError as ex:
        #     log.info(
        #         "Unable to fetch CI results due to a client problem. Not notifying user",
        #         extra=dict(repoid=commit.repoid, commit=commit.commitid, code=ex.code),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_GIT_CLIENT_ERROR)
        #     return {
        #         "notified": False,
        #         "notifications": None,
        #         "reason": "not_able_fetch_ci_result",
        #     }
        # except TorngitServerFailureError:
        #     log.info(
        #         "Unable to fetch CI results due to server issues. Not notifying user",
        #         extra=dict(repoid=commit.repoid, commit=commit.commitid),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_GIT_SERVICE_ERROR)
        #     return {
        #         "notified": False,
        #         "notifications": None,
        #         "reason": "server_issues_ci_result",
        #     }

        # Should not notify based on type of upload (empty upload)
        # Should not notify based on pending notifications




        if not notifications_called:
            UploadFlow.log(UploadFlow.SKIPPING_NOTIFICATION)





        ############## From processing

        log.debug("In finish_reports_processing for commit: %s" % commit)
        commitid = commit.commitid
        repoid = commit.repoid

        # always notify, let the notify handle if it should submit
        notifications_called = False
        if not regexp_ci_skip.search(commit.message or ""):
            match self.should_call_notifications(
                commit, commit_yaml, processing_results, report_code
            ):
                case ShouldCallNotifyResult.NOTIFY:
                    notifications_called = True
                    notify_kwargs = {
                        "repoid": repoid,
                        "commitid": commitid,
                        "current_yaml": commit_yaml.to_dict(),
                    }
                    notify_kwargs = UploadFlow.save_to_kwargs(notify_kwargs)
                    task = self.app.tasks[notify_task_name].apply_async(
                        kwargs=notify_kwargs
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
                    notify_error_kwargs = {
                        "repoid": repoid,
                        "commitid": commitid,
                        "current_yaml": commit_yaml.to_dict(),
                    }
                    notify_error_kwargs = UploadFlow.save_to_kwargs(notify_error_kwargs)
                    task = self.app.tasks[notify_error_task_name].apply_async(
                        kwargs=notify_error_kwargs
                    )
        else:
            commit.state = "skipped"

        UploadFlow.log(UploadFlow.PROCESSING_COMPLETE)
        if not notifications_called:
            UploadFlow.log(UploadFlow.SKIPPING_NOTIFICATION)

        return {"notifications_called": notifications_called}
        # except LockError:
        #     log.warning("Unable to acquire lock", extra=dict(lock_name=lock_name))
        #     UploadFlow.log(UploadFlow.FINISHER_LOCK_ERROR)

        ############## From processing

        ######### Possibly move this logic to the orchestrator task as a requirement
        try:
            installation_name_to_use = get_installation_name_for_owner_for_task(
                self.name, commit.repository.owner
            )
            repository_service = get_repo_provider_service_for_specific_commit(
                commit, installation_name_to_use
            )
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value
            )

            log.warning(
                "Unable to start notifications because repo doesn't have a valid bot",
                extra=dict(repoid=repoid, commit=commitid),
            )
            self.log_checkpoint(UploadFlow.NOTIF_NO_VALID_INTEGRATION)
            return {"notified": False, "notifications": None, "reason": "no_valid_bot"}
        except NoConfiguredAppsAvailable as exp:
            if exp.rate_limited_count > 0:
                # There's at least 1 app that we can use to communicate with GitHub,
                # but this app happens to be rate limited now. We try again later.
                # Min wait time of 1 minute
                retry_delay_seconds = max(60, get_seconds_to_next_hour())
                log.warning(
                    "Unable to start notifications. Retrying again later.",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        apps_available=exp.apps_count,
                        apps_rate_limited=exp.rate_limited_count,
                        apps_suspended=exp.suspended_count,
                        countdown_seconds=retry_delay_seconds,
                    ),
                )
                return self._attempt_retry(
                    max_retries=10,
                    countdown=retry_delay_seconds,
                    current_yaml=current_yaml,
                    commit=commit,
                    **kwargs,
                )
            # Maybe we have apps that are suspended. We can't communicate with github.
            log.warning(
                "We can't find an app to communicate with GitHub. Not notifying.",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    apps_available=exp.apps_count,
                    apps_suspended=exp.suspended_count,
                ),
            )
            self.log_checkpoint(UploadFlow.NOTIF_NO_APP_INSTALLATION)
            return {
                "notified": False,
                "notifications": None,
                "reason": "no_valid_github_app_found",
            }

        if current_yaml is None:
            current_yaml = async_to_sync(get_current_yaml)(commit, repository_service)
        else:
            current_yaml = UserYaml.from_dict(current_yaml)

        try:
            ci_results = self.fetch_and_update_whether_ci_passed(
                repository_service, commit, current_yaml
            )
        except TorngitClientError as ex:
            log.info(
                "Unable to fetch CI results due to a client problem. Not notifying user",
                extra=dict(repoid=commit.repoid, commit=commit.commitid, code=ex.code),
            )
            self.log_checkpoint(UploadFlow.NOTIF_GIT_CLIENT_ERROR)
            return {
                "notified": False,
                "notifications": None,
                "reason": "not_able_fetch_ci_result",
            }
        except TorngitServerFailureError:
            log.info(
                "Unable to fetch CI results due to server issues. Not notifying user",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            self.log_checkpoint(UploadFlow.NOTIF_GIT_SERVICE_ERROR)
            return {
                "notified": False,
                "notifications": None,
                "reason": "server_issues_ci_result",
            }
        if self.should_wait_longer(current_yaml, commit, ci_results):
            log.info(
                "Not sending notifications yet because we are waiting for CI to finish",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
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
            return self._attempt_retry(
                max_retries=max_retries,
                countdown=countdown,
                current_yaml=current_yaml,
                commit=commit,
                **kwargs,
            )

        report_service = ReportService(
            current_yaml, gh_app_installation_name=installation_name_to_use
        )
        head_report = report_service.get_existing_report_for_commit(
            commit, report_class=ReadOnlyReport
        )
        if self.should_send_notifications(
            current_yaml, commit, ci_results, head_report
        ):
            enriched_pull = async_to_sync(
                fetch_and_update_pull_request_information_from_commit
            )(repository_service, commit, current_yaml)
            if enriched_pull and enriched_pull.database_pull:
                pull = enriched_pull.database_pull
                base_commit = self.fetch_pull_request_base(pull)
            else:
                pull = None
                base_commit = self.fetch_parent(commit)

            if (
                enriched_pull
                and not self.send_notifications_if_commit_differs_from_pulls_head(
                    commit, enriched_pull, current_yaml
                )
                and empty_upload is None
            ):
                log.info(
                    "Not sending notifications for commit when it differs from pull's most recent head",
                    extra=dict(
                        commit=commit.commitid,
                        repoid=commit.repoid,
                        current_yaml=current_yaml.to_dict(),
                        pull_head=enriched_pull.provider_pull["head"]["commitid"],
                    ),
                )
                self.log_checkpoint(UploadFlow.NOTIF_STALE_HEAD)
                return {
                    "notified": False,
                    "notifications": None,
                    "reason": "User doesnt want notifications warning them that current head differs from pull request most recent head.",
                }

            if base_commit is not None:
                base_report = report_service.get_existing_report_for_commit(
                    base_commit, report_class=ReadOnlyReport
                )
            else:
                base_report = None
            if head_report is None and empty_upload is None:
                self.log_checkpoint(UploadFlow.NOTIF_ERROR_NO_REPORT)
                return {
                    "notified": False,
                    "notifications": None,
                    "reason": "no_head_report",
                }
            
        ######### Possibly move this logic to the orchestrator task as a requirement



        # log.info("Starting notifications", extra=dict(commit=commitid, repoid=repoid))
        # commits_query = db_session.query(Commit).filter(
        #     Commit.repoid == repoid, Commit.commitid == commitid
        # )
        # commit: Commit = commits_query.first()
        # assert commit, "Commit not found in database."

        # test_result_commit_report = commit.commit_report(ReportType.TEST_RESULTS)
        # if (
        #     test_result_commit_report is not None
        #     and test_result_commit_report.test_result_totals is not None
        #     and not test_result_commit_report.test_result_totals.error
        #     and test_result_commit_report.test_result_totals.failed > 0
        # ):
        #     return {
        #         "notify_attempted": False,
        #         "notifications": None,
        #         "reason": "test_failures",
        #     }

        # try:
        #     installation_name_to_use = get_installation_name_for_owner_for_task(
        #         self.name, commit.repository.owner
        #     )
        #     repository_service = get_repo_provider_service_for_specific_commit(
        #         commit, installation_name_to_use
        #     )
        # except RepositoryWithoutValidBotError:
        #     save_commit_error(
        #         commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value
        #     )

        #     log.warning(
        #         "Unable to start notifications because repo doesn't have a valid bot",
        #         extra=dict(repoid=repoid, commit=commitid),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_NO_VALID_INTEGRATION)
        #     return {"notified": False, "notifications": None, "reason": "no_valid_bot"}
        # except NoConfiguredAppsAvailable as exp:
        #     if exp.rate_limited_count > 0:
        #         # There's at least 1 app that we can use to communicate with GitHub,
        #         # but this app happens to be rate limited now. We try again later.
        #         # Min wait time of 1 minute
        #         retry_delay_seconds = max(60, get_seconds_to_next_hour())
        #         log.warning(
        #             "Unable to start notifications. Retrying again later.",
        #             extra=dict(
        #                 repoid=repoid,
        #                 commit=commitid,
        #                 apps_available=exp.apps_count,
        #                 apps_rate_limited=exp.rate_limited_count,
        #                 apps_suspended=exp.suspended_count,
        #                 countdown_seconds=retry_delay_seconds,
        #             ),
        #         )
        #         return self._attempt_retry(
        #             max_retries=10,
        #             countdown=retry_delay_seconds,
        #             current_yaml=current_yaml,
        #             commit=commit,
        #             **kwargs,
        #         )
        #     # Maybe we have apps that are suspended. We can't communicate with github.
        #     log.warning(
        #         "We can't find an app to communicate with GitHub. Not notifying.",
        #         extra=dict(
        #             repoid=repoid,
        #             commit=commitid,
        #             apps_available=exp.apps_count,
        #             apps_suspended=exp.suspended_count,
        #         ),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_NO_APP_INSTALLATION)
        #     return {
        #         "notified": False,
        #         "notifications": None,
        #         "reason": "no_valid_github_app_found",
        #     }

        # if current_yaml is None:
        #     current_yaml = async_to_sync(get_current_yaml)(commit, repository_service)
        # else:
        #     current_yaml = UserYaml.from_dict(current_yaml)

        # try:
        #     ci_results = self.fetch_and_update_whether_ci_passed(
        #         repository_service, commit, current_yaml
        #     )
        # except TorngitClientError as ex:
        #     log.info(
        #         "Unable to fetch CI results due to a client problem. Not notifying user",
        #         extra=dict(repoid=commit.repoid, commit=commit.commitid, code=ex.code),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_GIT_CLIENT_ERROR)
        #     return {
        #         "notified": False,
        #         "notifications": None,
        #         "reason": "not_able_fetch_ci_result",
        #     }
        # except TorngitServerFailureError:
        #     log.info(
        #         "Unable to fetch CI results due to server issues. Not notifying user",
        #         extra=dict(repoid=commit.repoid, commit=commit.commitid),
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIF_GIT_SERVICE_ERROR)
        #     return {
        #         "notified": False,
        #         "notifications": None,
        #         "reason": "server_issues_ci_result",
        #     }
        # if self.should_wait_longer(current_yaml, commit, ci_results):
        #     log.info(
        #         "Not sending notifications yet because we are waiting for CI to finish",
        #         extra=dict(repoid=commit.repoid, commit=commit.commitid),
        #     )
        #     ghapp_default_installations = list(
        #         filter(
        #             lambda obj: obj.name == installation_name_to_use
        #             and obj.is_configured(),
        #             commit.repository.owner.github_app_installations or [],
        #         )
        #     )
        #     rely_on_webhook_ghapp = ghapp_default_installations != [] and any(
        #         obj.is_repo_covered_by_integration(commit.repository)
        #         for obj in ghapp_default_installations
        #     )
        #     rely_on_webhook_legacy = commit.repository.using_integration
        #     if (
        #         rely_on_webhook_ghapp
        #         or rely_on_webhook_legacy
        #         or commit.repository.hookid
        #     ):
        #         # rely on the webhook, but still retry in case we miss the webhook
        #         max_retries = 5
        #         countdown = (60 * 3) * 2**self.request.retries
        #     else:
        #         max_retries = 10
        #         countdown = 15 * 2**self.request.retries
        #     return self._attempt_retry(
        #         max_retries=max_retries,
        #         countdown=countdown,
        #         current_yaml=current_yaml,
        #         commit=commit,
        #         **kwargs,
        #     )

        # report_service = ReportService(
        #     current_yaml, gh_app_installation_name=installation_name_to_use
        # )
        # head_report = report_service.get_existing_report_for_commit(
        #     commit, report_class=ReadOnlyReport
        # )
        # if self.should_send_notifications(
        #     current_yaml, commit, ci_results, head_report
        # ):
        #     enriched_pull = async_to_sync(
        #         fetch_and_update_pull_request_information_from_commit
        #     )(repository_service, commit, current_yaml)
        #     if enriched_pull and enriched_pull.database_pull:
        #         pull = enriched_pull.database_pull
        #         base_commit = self.fetch_pull_request_base(pull)
        #     else:
        #         pull = None
        #         base_commit = self.fetch_parent(commit)

        #     if (
        #         enriched_pull
        #         and not self.send_notifications_if_commit_differs_from_pulls_head(
        #             commit, enriched_pull, current_yaml
        #         )
        #         and empty_upload is None
        #     ):
        #         log.info(
        #             "Not sending notifications for commit when it differs from pull's most recent head",
        #             extra=dict(
        #                 commit=commit.commitid,
        #                 repoid=commit.repoid,
        #                 current_yaml=current_yaml.to_dict(),
        #                 pull_head=enriched_pull.provider_pull["head"]["commitid"],
        #             ),
        #         )
        #         self.log_checkpoint(UploadFlow.NOTIF_STALE_HEAD)
        #         return {
        #             "notified": False,
        #             "notifications": None,
        #             "reason": "User doesnt want notifications warning them that current head differs from pull request most recent head.",
        #         }

        #     if base_commit is not None:
        #         base_report = report_service.get_existing_report_for_commit(
        #             base_commit, report_class=ReadOnlyReport
        #         )
        #     else:
        #         base_report = None
        #     if head_report is None and empty_upload is None:
        #         self.log_checkpoint(UploadFlow.NOTIF_ERROR_NO_REPORT)
        #         return {
        #             "notified": False,
        #             "notifications": None,
        #             "reason": "no_head_report",
        #         }

        #     if commit.repository.service == "gitlab":
        #         gitlab_extra_shas_to_notify = self.get_gitlab_extra_shas_to_notify(
        #             commit, repository_service
        #         )
        #     else:
        #         gitlab_extra_shas_to_notify = None

        #     log.info(
        #         "We are going to be sending notifications",
        #         extra=dict(
        #             commit=commit.commitid,
        #             repoid=commit.repoid,
        #             current_yaml=current_yaml.to_dict(),
        #         ),
        #     )
        #     notifications = self.submit_third_party_notifications(
        #         current_yaml,
        #         base_commit,
        #         commit,
        #         base_report,
        #         head_report,
        #         enriched_pull,
        #         repository_service,
        #         empty_upload,
        #         all_tests_passed=(
        #             test_result_commit_report is not None
        #             and test_result_commit_report.test_result_totals is not None
        #             and test_result_commit_report.test_result_totals.error is None
        #             and test_result_commit_report.test_result_totals.failed == 0
        #         ),
        #         test_results_error=(
        #             test_result_commit_report is not None
        #             and test_result_commit_report.test_result_totals is not None
        #             and test_result_commit_report.test_result_totals.error
        #         ),
        #         installation_name_to_use=installation_name_to_use,
        #         gh_is_using_codecov_commenter=self.is_using_codecov_commenter(
        #             repository_service
        #         ),
        #         gitlab_extra_shas_to_notify=gitlab_extra_shas_to_notify,
        #     )
        #     self.log_checkpoint(UploadFlow.NOTIFIED)
        #     log.info(
        #         "Notifications done",
        #         extra=dict(
        #             notifications=notifications,
        #             notification_count=len(notifications),
        #             commit=commit.commitid,
        #             repoid=commit.repoid,
        #             pullid=pull.pullid if pull is not None else None,
        #         ),
        #     )
        #     db_session.commit()
        #     return {"notified": True, "notifications": notifications}
        # else:
        #     log.info(
        #         "Not sending notifications at all",
        #         extra=dict(commit=commit.commitid, repoid=commit.repoid),
        #     )
        #     self.log_checkpoint(UploadFlow.SKIPPING_NOTIFICATION)
        #     return {"notified": False, "notifications": None}




    # def log_checkpoint(self, checkpoint):
    #     """
    #     Only log a checkpoint if whoever scheduled us sent checkpoints data from
    #     the same flow.

    #     The notify task is an important part of `UploadFlow`, but it's also used
    #     elsewhere. If this instance of the notify task wasn't scheduled as part
    #     of upload processing, attempting to log `UploadFlow` checkpoints for it
    #     will pollute our metrics.
    #     """
    #     if UploadFlow.has_begun():
    #         UploadFlow.log(checkpoint)

    # Notify task signature
                    # notify_kwargs = {
    #                     "repoid": repoid,
    #                     "commitid": commitid,
    #                     "current_yaml": commit_yaml.to_dict(),
    #                 }
    #                 notify_kwargs = UploadFlow.save_to_kwargs(notify_kwargs)
    #                 task = self.app.tasks[notify_task_name].apply_async(
    #                     kwargs=notify_kwargs
    #                 )


    def _attempt_retry(
        self,
        max_retries: int,
        countdown: int,
        commit: Commit,
        current_yaml: Optional[UserYaml],
        *args,
        **kwargs,
    ) -> None:
        try:
            self.retry(max_retries=max_retries, countdown=countdown)
        except MaxRetriesExceededError:
            log.warning(
                "Not attempting to retry notifications since we already retried too many times",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    max_retries=max_retries,
                    next_countdown_would_be=countdown,
                    current_yaml=current_yaml.to_dict(),
                ),
            )
            self.log_checkpoint(UploadFlow.NOTIF_TOO_MANY_RETRIES)
            return {
                "notified": False,
                "notifications": None,
                "reason": "too_many_retries",
            }

RegisteredNotificationOrchestratorTask = celery_app.register_task(NotificationOrchestratorTask())
notification_orchestrator_task = celery_app.tasks[RegisteredNotificationOrchestratorTask.name]