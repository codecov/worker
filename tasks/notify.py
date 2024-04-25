import logging
from typing import Optional

from asgiref.sync import async_to_sync
from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
from shared.celery_config import (
    new_user_activated_task_name,
    notify_task_name,
    status_set_error_task_name,
)
from shared.reports.readonly import ReadOnlyReport
from shared.torngit.exceptions import TorngitClientError, TorngitServerFailureError
from shared.yaml import UserYaml
from sqlalchemy import desc
from sqlalchemy.orm.session import Session
from test_results_parser import Outcome

from app import celery_app
from database.enums import CommitErrorTypes, Decoration, ReportType
from database.models import Commit, Pull
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import UploadFlow
from helpers.clock import get_seconds_to_next_hour
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from helpers.save_commit_error import save_commit_error
from services.activation import activate_user
from services.billing import BillingPlan
from services.commit_status import RepositoryCIFilter
from services.comparison import ComparisonProxy, NotificationContext
from services.comparison.types import Comparison, FullCommit
from services.decoration import determine_decoration_details
from services.lock_manager import LockManager, LockRetry, LockType
from services.notification import NotificationService
from services.redis import Redis, get_redis_connection
from services.report import ReportService
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.test_results import latest_test_instances_for_a_given_commit
from services.yaml import get_current_yaml, read_yaml_field
from tasks.base import BaseCodecovTask
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME

log = logging.getLogger(__name__)


class NotifyTask(BaseCodecovTask, name=notify_task_name):
    throws = (SoftTimeLimitExceeded,)

    def run_impl(
        self,
        db_session: Session,
        *,
        repoid: int,
        commitid: str,
        current_yaml=None,
        empty_upload=None,
        **kwargs,
    ):
        redis_connection = get_redis_connection()
        if self.has_upcoming_notifies_according_to_redis(
            redis_connection, repoid, commitid
        ):
            log.info(
                "Not notifying because there are seemingly other jobs being processed yet",
                extra=dict(repoid=repoid, commitid=commitid),
            )
            # Should we log an UploadFlow checkpoint here?
            return {
                "notified": False,
                "notifications": None,
                "reason": "has_other_notifies_coming",
            }

        lock_manager = LockManager(
            repoid=repoid,
            commitid=commitid,
            report_type=ReportType.COVERAGE,
            lock_timeout=max(80, self.hard_time_limit_task),
        )

        try:
            lock_acquired = False
            with lock_manager.locked(
                lock_type=LockType.NOTIFICATION, retry_num=self.request.retries
            ):
                lock_acquired = True
                return self.run_impl_within_lock(
                    db_session,
                    repoid=repoid,
                    commitid=commitid,
                    current_yaml=current_yaml,
                    empty_upload=empty_upload,
                    **kwargs,
                )
        except LockRetry as err:
            log.info(
                "Not notifying because there is another notification already happening",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    error_type=type(err),
                    lock_acquired=lock_acquired,
                ),
            ),
            self.log_checkpoint(kwargs, UploadFlow.NOTIF_LOCK_ERROR)
            return {
                "notified": False,
                "notifications": None,
                "reason": "unobtainable_lock",
            }

    def log_checkpoint(self, kwargs, checkpoint):
        """
        Only log a checkpoint if whoever scheduled us sent checkpoints data from
        the same flow.

        The notify task is an important part of `UploadFlow`, but it's also used
        elsewhere. If this instance of the notify task wasn't scheduled as part
        of upload processing, attempting to log `UploadFlow` checkpoints for it
        will pollute our metrics.
        """
        checkpoints = checkpoints_from_kwargs(checkpoint.__class__, kwargs)
        if checkpoints.data:
            checkpoints.log(checkpoint)

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
            self.log_checkpoint(kwargs, UploadFlow.NOTIF_TOO_MANY_RETRIES)
            return {
                "notified": False,
                "notifications": None,
                "reason": "too_many_retries",
            }

    def run_impl_within_lock(
        self,
        db_session: Session,
        *,
        repoid: int,
        commitid: str,
        current_yaml=None,
        empty_upload=None,
        **kwargs,
    ):
        log.info("Starting notifications", extra=dict(commit=commitid, repoid=repoid))
        commits_query = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit: Commit = commits_query.first()

        test_result_commit_report = commit.commit_report(ReportType.TEST_RESULTS)
        if (
            test_result_commit_report is not None
            and test_result_commit_report.test_result_totals is not None
            and not test_result_commit_report.test_result_totals.error
            and test_result_commit_report.test_result_totals.failed > 0
        ):
            return {
                "notify_attempted": False,
                "notifications": None,
                "reason": "test_failures",
            }

        try:
            installation_name_to_use = None
            if commit.repository.owner.service in ["github", "github_enterprise"]:
                installation_name_to_use = get_installation_name_for_owner_for_task(
                    db_session, self.name, commit.repository.owner
                )
            repository_service = get_repo_provider_service(
                commit.repository, installation_name_to_use=installation_name_to_use
            )
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value
            )

            log.warning(
                "Unable to start notifications because repo doesn't have a valid bot",
                extra=dict(repoid=repoid, commit=commitid),
            )
            self.log_checkpoint(kwargs, UploadFlow.NOTIF_NO_VALID_INTEGRATION)
            return {"notified": False, "notifications": None, "reason": "no_valid_bot"}
        except NoConfiguredAppsAvailable as exp:
            # Min wait time of 1 minute
            retry_delay_seconds = max(60, get_seconds_to_next_hour())
            log.warning(
                "Unable to start notifications because all ghapps available are rate limited",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    apps_available=exp.apps_count,
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

        if current_yaml is None:
            current_yaml = async_to_sync(get_current_yaml)(commit, repository_service)
        else:
            current_yaml = UserYaml.from_dict(current_yaml)
        assert commit, "Commit not found in database."
        try:
            ci_results = self.fetch_and_update_whether_ci_passed(
                repository_service, commit, current_yaml
            )
        except TorngitClientError as ex:
            log.info(
                "Unable to fetch CI results due to a client problem. Not notifying user",
                extra=dict(repoid=commit.repoid, commit=commit.commitid, code=ex.code),
            )
            self.log_checkpoint(kwargs, UploadFlow.NOTIF_GIT_CLIENT_ERROR)
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
            self.log_checkpoint(kwargs, UploadFlow.NOTIF_GIT_SERVICE_ERROR)
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

        report_service = ReportService(current_yaml)
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
                self.log_checkpoint(kwargs, UploadFlow.NOTIF_STALE_HEAD)
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
            head_report = report_service.get_existing_report_for_commit(
                commit, report_class=ReadOnlyReport
            )
            if head_report is None and empty_upload is None:
                self.log_checkpoint(kwargs, UploadFlow.NOTIF_ERROR_NO_REPORT)
                return {
                    "notified": False,
                    "notifications": None,
                    "reason": "no_head_report",
                }
            log.info(
                "We are going to be sending notifications",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    current_yaml=current_yaml.to_dict(),
                ),
            )
            notifications = self.submit_third_party_notifications(
                current_yaml,
                base_commit,
                commit,
                base_report,
                head_report,
                enriched_pull,
                empty_upload,
                all_tests_passed=(
                    test_result_commit_report is not None
                    and test_result_commit_report.test_result_totals is not None
                    and test_result_commit_report.test_result_totals.error is None
                    and test_result_commit_report.test_result_totals.failed == 0
                ),
                test_results_error=(
                    test_result_commit_report is not None
                    and test_result_commit_report.test_result_totals is not None
                    and test_result_commit_report.test_result_totals.error
                ),
                installation_name_to_use=installation_name_to_use,
            )
            self.log_checkpoint(kwargs, UploadFlow.NOTIFIED)
            log.info(
                "Notifications done",
                extra=dict(
                    notifications=notifications,
                    notification_count=len(notifications),
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    pullid=pull.pullid if pull is not None else None,
                ),
            )
            db_session.commit()
            commit.notified = True
            db_session.commit()
            return {"notified": True, "notifications": notifications}
        else:
            log.info(
                "Not sending notifications at all",
                extra=dict(commit=commit.commitid, repoid=commit.repoid),
            )
            return {"notified": False, "notifications": None}

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

    def submit_third_party_notifications(
        self,
        current_yaml: UserYaml,
        base_commit,
        commit,
        base_report,
        head_report,
        enriched_pull: EnrichedPull,
        empty_upload=None,
        # It's only true if the test_result processing is setup
        # And all tests indeed passed
        all_tests_passed: bool = False,
        test_results_error: bool = False,
        installation_name_to_use: str = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    ):
        # base_commit is an "adjusted" base commit; for project coverage, we
        # compare a PR head's report against its base's report, or if the base
        # doesn't exist in our database, the next-oldest commit that does. That
        # is unnecessary/incorrect for patch coverage, for which we want to
        # compare against the original PR base.
        pull = enriched_pull.database_pull if enriched_pull else None
        if pull:
            patch_coverage_base_commitid = pull.base
        elif base_commit is not None:
            patch_coverage_base_commitid = base_commit.commitid
        else:
            log.warning(
                "Neither the original nor updated base commit are known",
                extra=dict(repoid=commit.repository.repoid, commit=commit.commitid),
            )
            patch_coverage_base_commitid = None

        comparison = ComparisonProxy(
            Comparison(
                head=FullCommit(commit=commit, report=head_report),
                enriched_pull=enriched_pull,
                project_coverage_base=FullCommit(
                    commit=base_commit, report=base_report
                ),
                patch_coverage_base_commitid=patch_coverage_base_commitid,
                current_yaml=current_yaml,
            ),
            context=NotificationContext(
                all_tests_passed=all_tests_passed, test_results_error=test_results_error
            ),
        )

        decoration_type = self.determine_decoration_type_from_pull(
            enriched_pull, empty_upload
        )

        notifications_service = NotificationService(
            commit.repository,
            current_yaml,
            decoration_type,
            gh_installation_name_to_use=installation_name_to_use,
        )
        return async_to_sync(notifications_service.notify)(comparison)

    def send_notifications_if_commit_differs_from_pulls_head(
        self, commit, enriched_pull, current_yaml
    ):
        if (
            enriched_pull.provider_pull is not None
            and commit.commitid != enriched_pull.provider_pull["head"]["commitid"]
        ):
            wait_for_ci = read_yaml_field(
                current_yaml, ("codecov", "notify", "wait_for_ci")
            )
            manual_trigger = read_yaml_field(
                current_yaml, ("codecov", "notify", "manual_trigger")
            )
            after_n_builds = read_yaml_field(
                current_yaml, ("codecov", "notify", "after_n_builds")
            )
            if wait_for_ci or manual_trigger or after_n_builds:
                return False
        return True

    def fetch_pull_request_base(self, pull: Pull) -> Commit:
        return pull.get_comparedto_commit()

    def fetch_parent(self, commit):
        db_session = commit.get_db_session()
        return (
            db_session.query(Commit)
            .filter_by(commitid=commit.parent_commit_id, repoid=commit.repoid)
            .first()
        )

    def should_send_notifications(self, current_yaml, commit, ci_passed, report):
        if (
            read_yaml_field(current_yaml, ("codecov", "require_ci_to_pass"), True)
            and ci_passed is False
        ):
            # we can exit, ci failed.
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

        # check the nuber of builds
        after_n_builds = read_yaml_field(
            current_yaml, ("codecov", "notify", "after_n_builds")
        )
        if after_n_builds:
            number_sessions = len(report.sessions) if report is not None else 0
            if after_n_builds > number_sessions:
                log.info(
                    "Not sending notifications because there arent enough builds",
                    extra=dict(
                        repoid=commit.repoid,
                        commit=commit.commitid,
                        after_n_builds=after_n_builds,
                        number_sessions=number_sessions,
                    ),
                )
                return False
        return True

    def should_wait_longer(self, current_yaml, commit, ci_results):
        return (
            read_yaml_field(current_yaml, ("codecov", "notify", "wait_for_ci"), True)
            and ci_results is None
        )

    def determine_decoration_type_from_pull(
        self,
        enriched_pull: EnrichedPull,
        empty_upload=None,
    ) -> Decoration:
        """
        Get and process decoration details and attempt auto activation if necessary
        """
        decoration_details = determine_decoration_details(enriched_pull, empty_upload)
        decoration_type = decoration_details.decoration_type

        if decoration_details.should_attempt_author_auto_activation:
            successful_activation = activate_user(
                enriched_pull.database_pull.get_db_session(),
                decoration_details.activation_org_ownerid,
                decoration_details.activation_author_ownerid,
            )
            if successful_activation:
                self.schedule_new_user_activated_task(
                    decoration_details.activation_org_ownerid,
                    decoration_details.activation_author_ownerid,
                )
                decoration_type = Decoration.standard
        return decoration_type

    def schedule_new_user_activated_task(self, org_ownerid, user_ownerid):
        celery_app.send_task(
            new_user_activated_task_name,
            args=None,
            kwargs=dict(org_ownerid=org_ownerid, user_ownerid=user_ownerid),
        )

    def fetch_and_update_whether_ci_passed(
        self, repository_service, commit, current_yaml
    ):
        all_statuses = async_to_sync(repository_service.get_commit_statuses)(
            commit.commitid
        )
        ci_state = all_statuses.filter(RepositoryCIFilter(current_yaml))
        if ci_state:
            # cannot use instead of "codecov/*" because
            # [bitbucket] appends the extra "codecov-" to the status
            # which becomes "codecov-codecov/patch"
            ci_state = ci_state - "codecov*"
        ci_passed = (
            True if ci_state.is_success else False if ci_state.is_failure else None
        )
        if ci_passed != commit.ci_passed:
            commit.ci_passed = ci_passed
        return ci_passed


RegisteredNotifyTask = celery_app.register_task(NotifyTask())
notify_task = celery_app.tasks[RegisteredNotifyTask.name]
