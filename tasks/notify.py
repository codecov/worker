import logging

from sqlalchemy.orm.session import Session
from torngit.exceptions import TorngitClientError, TorngitServerFailureError
from celery.exceptions import MaxRetriesExceededError

from app import celery_app
from celery_config import (
    notify_task_name, status_set_error_task_name, task_default_queue
)
from database.models import Commit, Pull
from helpers.exceptions import RepositoryWithoutValidBotError
from services.commit_status import RepositoryCIFilter
from services.notification.types import Comparison, FullCommit
from services.notification import NotificationService
from services.report import ReportService
from services.repository import (
    get_repo_provider_service, fetch_and_update_pull_request_information_from_commit
)
from services.yaml import read_yaml_field
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


def default_if_true(value):
    if value is True:
        yield 'default', {}
    elif type(value) is dict:
        for key, data in value.items():
            if data is False:
                continue
            elif data is True:
                yield key, {}
            elif type(data) is not dict or data.get('enabled') is False:
                continue
            else:
                yield key, data


class NotifyTask(BaseCodecovTask):

    name = notify_task_name

    async def run_async(self, db_session: Session, repoid: int, commitid: str, current_yaml=None, *args, **kwargs):
        log.info(
            "Starting notifications",
            extra=dict(
                commit=commitid,
                repoid=repoid
            )
        )
        commits_query = db_session.query(Commit).filter(
                Commit.repoid == repoid, Commit.commitid == commitid)
        commit = commits_query.first()
        try:
            repository_service = get_repo_provider_service(commit.repository)
        except RepositoryWithoutValidBotError:
            log.warning(
                "Unable to start notifications because repo doesn't have a valid bot",
                extra=dict(
                    repoid=repoid,
                    commit=commitid
                )
            )
            return {
                'notified': False,
                'notifications': None,
                'reason': 'no_valid_bot'
            }
        if current_yaml is None:
            current_yaml = await fetch_commit_yaml_from_provider(commit, repository_service)
        assert commit, 'Commit not found in database.'
        try:
            ci_results = await self.fetch_and_update_whether_ci_passed(
                repository_service, commit, current_yaml
            )
        except TorngitClientError as ex:
            log.info(
                "Unable to fetch CI results due to a client problem. Not notifying user",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    code=ex.code
                )
            )
            return {
                'notified': False,
                'notifications': None,
                'reason': 'not_able_fetch_ci_result'
            }
        except TorngitServerFailureError:
            log.info(
                "Unable to fetch CI results due to server issues. Not notifying user",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                )
            )
            return {
                'notified': False,
                'notifications': None,
                'reason': 'server_issues_ci_result'
            }
        if self.should_wait_longer(current_yaml, commit, ci_results):
            log.info(
                'Not sending notifications yet because we are waiting for CI to finish',
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid
                )
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
                        current_yaml=current_yaml
                    )
                )
                return {
                    'notified': False,
                    'notifications': None,
                    'reason': 'too_many_retries'
                }
        if self.should_send_notifications(current_yaml, commit, ci_results):
            log.info(
                "We are going to be sending notifications",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid
                )
            )
            enriched_pull = await fetch_and_update_pull_request_information_from_commit(
                repository_service, commit, current_yaml
            )
            if enriched_pull:
                pull = enriched_pull.database_pull
                base_commit = self.fetch_pull_request_base(pull)
            else:
                pull = None
                base_commit = self.fetch_parent(commit)
            report_service = ReportService(current_yaml)
            if base_commit is not None:
                base_report = report_service.build_report_from_commit(base_commit)
            else:
                base_report = None
            head_report = report_service.build_report_from_commit(commit)
            notifications = await self.submit_third_party_notifications(
                current_yaml, base_commit, commit, base_report, head_report, pull
            )
            log.info(
                "Notifications done",
                extra=dict(
                    notifications=notifications,
                    commitid=commit.commitid,
                    repoid=commit.repoid,
                    pullid=pull.pullid if pull is not None else None
                )
            )
            commit.notified = True
            return {
                'notified': True,
                'notifications': notifications
            }
        else:
            log.info(
                "Not sending notifications at all",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid
                )
            )
            return {
                'notified': False,
                'notifications': None
            }

    async def submit_third_party_notifications(self, current_yaml, base_commit, commit, base_report, head_report, pull):
        comparison = Comparison(
            head=FullCommit(
                commit=commit,
                report=head_report
            ),
            pull=pull,
            base=FullCommit(
                commit=base_commit,
                report=base_report
            ),
        )
        notifications_service = NotificationService(commit.repository, current_yaml)
        return await notifications_service.notify(comparison)

    def fetch_pull_request_base(self, pull: Pull) -> Commit:
        return pull.get_comparedto_commit()

    def fetch_parent(self, commit):
        db_session = commit.get_db_session()
        return db_session.query(Commit).filter_by(
            commitid=commit.parent_commit_id,
            repoid=commit.repoid
        ).first()

    def should_send_notifications(self, current_yaml, commit, ci_passed):
        if (
            read_yaml_field(current_yaml, ('codecov', 'require_ci_to_pass'), True) and
            ci_passed is False
        ):
            # we can exit, ci failed.
            self.app.tasks[status_set_error_task_name].apply_async(
                args=None,
                kwargs=dict(
                    repoid=commit.repoid,
                    commitid=commit.commitid,
                    message='CI failed.'
                ),
                queue=task_default_queue
            )
            log.info(
                'Not sending notifications because CI failed',
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                )
            )
            return False

        # check the nuber of builds
        after_n_builds = read_yaml_field(current_yaml, ('codecov', 'notify', 'after_n_builds'))
        if after_n_builds:
            number_sessions = 0
            if commit.report_json:
                number_sessions = len(commit.report_json.get('sessions', {}))
            if after_n_builds > number_sessions:
                log.info(
                    'Not sending notifications because there arent enough builds',
                    extra=dict(
                        repoid=commit.repoid,
                        commit=commit.commitid,
                        after_n_builds=after_n_builds,
                        number_sessions=number_sessions
                    )
                )
                return False
        return True

    def should_wait_longer(self, current_yaml, commit, ci_results):
        return (
            read_yaml_field(current_yaml, ('codecov', 'notify', 'wait_for_ci'), True) and
            ci_results is None
        )

    async def fetch_and_update_whether_ci_passed(self, repository_service, commit, current_yaml):
        all_statuses = await repository_service.get_commit_statuses(commit.commitid)
        ci_state = all_statuses.filter(RepositoryCIFilter(current_yaml))
        if ci_state:
            # cannot use instead of "codecov/*" because
            # [bitbucket] appends the extra "codecov-" to the status
            # which becomes "codecov-codecov/patch"
            ci_state = ci_state - 'codecov*'
        ci_passed = True if ci_state.is_success else False if ci_state.is_failure else None
        if ci_passed != commit.ci_passed:
            commit.ci_passed = ci_passed
        return ci_passed


RegisteredNotifyTask = celery_app.register_task(NotifyTask())
notify_task = celery_app.tasks[RegisteredNotifyTask.name]
