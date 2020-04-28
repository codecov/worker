from database.enums import Notification
from database.models import Pull, PullNotification
from services.notification.notifiers.base import (
    NotificationResult,
    AbstractBaseNotifier,
)


def create_or_update_pull_notification_from_notification_result(
    pull: Pull, notifier: AbstractBaseNotifier, result_dict
):
    if not pull:
        # TODO: is it possible to not have pull or just test cases not fully accurate?
        return

    db_session = pull.get_db_session()

    attempted = result_dict.get("notification_attempted") if result_dict else True
    successful = result_dict.get("notification_successful") if result_dict else False

    pull_notification = (
        db_session.query(PullNotification)
        .filter(
            PullNotification.repoid == pull.repoid,
            PullNotification.pullid == pull.pullid,
            PullNotification.notification == notifier.notification_type,
        )
        .first()
    )

    if not pull_notification:
        pull_notification = PullNotification(
            repoid=pull.repoid,
            pullid=pull.pullid,
            notification=notifier.notification_type,
            attempted=attempted,
            successful=successful,
            decoration=notifier.decoration_type,
        )
        db_session.add(pull_notification)
        db_session.flush()
        return pull_notification

    pull_notification.decoration = notifier.decoration_type

    # 'attempted' defaults to False. We check to make sure we don't change from True -> False
    if pull_notification.attempted is False and attempted:
        pull_notification.attempted = True

    # 'successful' can be null in DB. we check to make sure we don't change from True -> False/None
    if not pull_notification.successful and successful is not None:
        pull_notification.successful = successful

    return pull_notification
