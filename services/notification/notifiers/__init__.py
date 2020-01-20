from services.notification.notifiers.gitter import GitterNotifier
from services.notification.notifiers.hipchat import HipchatNotifier
from services.notification.notifiers.irc import IRCNotifier
from services.notification.notifiers.slack import SlackNotifier
from services.notification.notifiers.webhook import WebhookNotifier
from services.notification.notifiers.comment import CommentNotifier
from services.notification.notifiers.status import (
    ProjectStatusNotifier,
    PatchStatusNotifier,
    ChangesStatusNotifier
)


def get_all_notifier_classes_mapping():
    return {
        'gitter': GitterNotifier,
        'hipchat': HipchatNotifier,
        'irc': IRCNotifier,
        'slack': SlackNotifier,
        'webhook': WebhookNotifier
    }


def get_status_notifier_class(status_type: str):
    if status_type == 'patch':
        return PatchStatusNotifier
    if status_type == 'project':
        return ProjectStatusNotifier
    if status_type == 'changes':
        return ChangesStatusNotifier


def get_pull_request_notifiers():
    return [
        CommentNotifier
    ]
