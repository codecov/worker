import logging

from sqlalchemy.orm.session import Session

from database.enums import NotificationState
from database.models import CommitNotification, Pull
from helpers.metrics import metrics
from services.comparison import ComparisonProxy
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)

log = logging.getLogger(__name__)


def _get_notification_state_from_result(
    notification_result: NotificationResult | None,
) -> NotificationState:
    """
    Take notification result from notification service and convert to
    the proper NotificationState enum
    """
    if notification_result is None:
        return NotificationState.error

    successful = notification_result.notification_successful

    if successful:
        return NotificationState.success
    else:
        return NotificationState.error


@metrics.timer("internal.services.notification.store_notification_result")
def create_or_update_commit_notification_from_notification_result(
    comparison: ComparisonProxy,
    notifier: AbstractBaseNotifier,
    notification_result: NotificationResult | None,
) -> CommitNotification:
    """Saves a CommitNotification entry in the database.
    We save an entry in the following scenarios:
        - We save all notification attempts for commits that are part of a PullRequest
        - We save _successful_ notification attempt _with_ a github app
    """
    pull: Pull | None = comparison.pull
    not_pull = pull is None
    not_head_commit = comparison.head is None or comparison.head.commit is None
    not_github_app_info = (
        notification_result is None or notification_result.github_app_used is None
    )
    failed = (
        notification_result is None
        or notification_result.notification_successful == False
    )
    if not_pull and (not_head_commit or not_github_app_info or failed):
        return

    commit = pull.get_head_commit() if pull else comparison.head.commit
    if not commit:
        log.warning("Head commit not found for pull", extra=dict(pull=pull))
        return

    db_session: Session = commit.get_db_session()

    commit_notification = (
        db_session.query(CommitNotification)
        .filter(
            CommitNotification.commit_id == commit.id_,
            CommitNotification.notification_type == notifier.notification_type,
        )
        .first()
    )

    notification_state = _get_notification_state_from_result(notification_result)
    github_app_used = (
        notification_result.github_app_used if notification_result else None
    )

    if not commit_notification:
        commit_notification = CommitNotification(
            commit_id=commit.id_,
            notification_type=notifier.notification_type,
            decoration_type=notifier.decoration_type,
            gh_app_id=github_app_used,
            state=notification_state,
        )
        db_session.add(commit_notification)
        db_session.flush()
        return commit_notification

    commit_notification.decoration_type = notifier.decoration_type
    commit_notification.state = notification_state
    return commit_notification
