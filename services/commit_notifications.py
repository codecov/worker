import logging

from database.enums import Notification, NotificationState
from database.models import Pull, CommitNotification
from services.notification.notifiers.base import (
    NotificationResult,
    AbstractBaseNotifier,
)

log = logging.getLogger(__name__)


def get_notification_state_from_result(result_dict) -> NotificationState:
    """
    Take notification result_dict from notification service and convert to
    the proper NotificationState enum
    """
    if result_dict is None:
        return NotificationState.error

    attempted = result_dict.get("notification_attempted", True)
    successful = result_dict.get("notification_successful")

    if successful:
        return NotificationState.success
    elif successful is False:
        return NotificationState.error
    else:
        return NotificationState.pending


def create_or_update_commit_notification_from_notification_result(
    pull: Pull, notifier: AbstractBaseNotifier, result_dict
) -> CommitNotification:
    if not pull:
        return

    db_session = pull.get_db_session()

    commit = pull.get_head_commit()
    if not commit:
        log.warning("Head commit not found for pull", extra=dict(pull=pull))
        return

    commit_notification = (
        db_session.query(CommitNotification)
        .filter(
            CommitNotification.commitid == commit.id_,
            CommitNotification.notification_type == notifier.notification_type,
        )
        .first()
    )

    notification_state = get_notification_state_from_result(result_dict)

    if not commit_notification:
        commit_notification = CommitNotification(
            commitid=commit.id_,
            notification_type=notifier.notification_type,
            decoration_type=notifier.decoration_type,
            state=notification_state,
        )
        db_session.add(commit_notification)
        db_session.flush()
        return commit_notification

    commit_notification.decoration_type = notifier.decoration_type
    commit_notification.state = notification_state
    return commit_notification
