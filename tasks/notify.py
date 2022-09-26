import logging

from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.celery_config import (
    new_user_activated_task_name,
    notify_task_name,
    status_set_error_task_name,
)
from shared.reports.readonly import ReadOnlyReport
from shared.torngit.exceptions import TorngitClientError, TorngitServerFailureError
from shared.yaml import UserYaml
from sqlalchemy.orm.session import Session

from app import celery_app
from database.enums import CommitErrorTypes, Decoration
from database.models import Commit, Pull
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.save_commit_error import save_commit_error
from services.activation import activate_user
from services.commit_status import RepositoryCIFilter
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.decoration import determine_decoration_details
from services.notification import NotificationService
from services.redis import Redis, get_redis_connection
from services.report import ReportService
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.yaml import get_current_yaml, read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class NotifyTask(BaseCodecovTask):

    name = notify_task_name

    throws = (SoftTimeLimitExceeded,)

    async def run_async(
        self,
        db_session: Session,
        *,
        repoid: int,
        commitid: str,
        current_yaml=None,
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
            return {
                "notified": False,
                "notifications": None,
                "reason": "has_other_notifies_coming",
            }
        notify_lock_name = f"notify_lock_{repoid}_{commitid}"
        try:
            with redis_connection.lock(
                notify_lock_name,
                timeout=max(80, self.hard_time_limit_task),
                blocking_timeout=10,
            ):
                return await self.run_async_within_lock(
                    db_session,
                    repoid=repoid,
                    commitid=commitid,
                    current_yaml=current_yaml,
                    **kwargs,
                )
        except LockError:
            log.info(
                "Not notifying because there is another notification already happening",
                extra=dict(repoid=repoid, commitid=commitid),
            )
            return {
                "notified": False,
                "notifications": None,
                "reason": "unobtainable_lock",
            }

    async def run_async_within_lock(
        self,
        db_session: Session,
        *,
        repoid: int,
        commitid: str,
        current_yaml=None,
        **kwargs,
    ):
        log.info("Starting notifications", extra=dict(commit=commitid, repoid=repoid))
        commits_query = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits_query.first()
        try:
            repository_service = get_repo_provider_service(commit.repository)
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value
            )

            log.warning(
                "Unable to start notifications because repo doesn't have a valid bot",
                extra=dict(repoid=repoid, commit=commitid),
            )
            return {"notified": False, "notifications": None, "reason": "no_valid_bot"}
        if current_yaml is None:
            current_yaml = await get_current_yaml(commit, repository_service)
        else:
            current_yaml = UserYaml.from_dict(current_yaml)
        assert commit, "Commit not found in database."
        try:
            ci_results = await self.fetch_and_update_whether_ci_passed(
                repository_service, commit, current_yaml
            )
        except TorngitClientError as ex:
            log.info(
                "Unable to fetch CI results due to a client problem. Not notifying user",
                extra=dict(repoid=commit.repoid, commit=commit.commitid, code=ex.code),
            )
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
            if commit.repository.using_integration or commit.repository.hookid:
                # rely on the webhook, but still retry in case we miss the webhook
                max_retries = 5
                countdown = (60 * 3) * 2**self.request.retries
            else:
                max_retries = 10
                countdown = 15 * 2**self.request.retries
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
                return {
                    "notified": False,
                    "notifications": None,
                    "reason": "too_many_retries",
                }
        if self.should_send_notifications(current_yaml, commit, ci_results):
            log.info(
                "We are going to be sending notifications",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    current_yaml=current_yaml.to_dict(),
                ),
            )
            enriched_pull = await fetch_and_update_pull_request_information_from_commit(
                repository_service, commit, current_yaml
            )
            if enriched_pull and enriched_pull.database_pull:
                pull = enriched_pull.database_pull
                base_commit = self.fetch_pull_request_base(pull)
            else:
                pull = None
                base_commit = self.fetch_parent(commit)

            report_service = ReportService(current_yaml)
            if base_commit is not None:
                base_report = report_service.get_existing_report_for_commit(
                    base_commit, report_class=ReadOnlyReport
                )
            else:
                base_report = None
            head_report = report_service.get_existing_report_for_commit(
                commit, report_class=ReadOnlyReport
            )
            if head_report is None:
                return {
                    "notified": False,
                    "notifications": None,
                    "reason": "no_head_report",
                }
            notifications = await self.submit_third_party_notifications(
                current_yaml,
                base_commit,
                commit,
                base_report,
                head_report,
                enriched_pull,
            )
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
        upload_processing_lock_name = f"upload_processing_lock_{repoid}_{commitid}"
        if redis_connection.get(upload_processing_lock_name):
            return True
        return False

    async def submit_third_party_notifications(
        self,
        current_yaml: UserYaml,
        base_commit,
        commit,
        base_report,
        head_report,
        enriched_pull: EnrichedPull,
    ):
        comparison = ComparisonProxy(
            Comparison(
                head=FullCommit(commit=commit, report=head_report),
                enriched_pull=enriched_pull,
                base=FullCommit(commit=base_commit, report=base_report),
            )
        )

        decoration_type = self.determine_decoration_type_from_pull(enriched_pull)

        notifications_service = NotificationService(
            commit.repository, current_yaml, decoration_type
        )
        return await notifications_service.notify(comparison)

    def fetch_pull_request_base(self, pull: Pull) -> Commit:
        return pull.get_comparedto_commit()

    def fetch_parent(self, commit):
        db_session = commit.get_db_session()
        return (
            db_session.query(Commit)
            .filter_by(commitid=commit.parent_commit_id, repoid=commit.repoid)
            .first()
        )

    def should_send_notifications(self, current_yaml, commit, ci_passed):
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
            number_sessions = 0
            if commit.report_json:
                number_sessions = len(commit.report_json.get("sessions", {}))
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
        self, enriched_pull: EnrichedPull
    ) -> Decoration:
        """
        Get and process decoration details and attempt auto activation if necessary
        """
        decoration_details = determine_decoration_details(enriched_pull)
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

    async def fetch_and_update_whether_ci_passed(
        self, repository_service, commit, current_yaml
    ):
        all_statuses = await repository_service.get_commit_statuses(commit.commitid)
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
