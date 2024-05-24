from enum import Enum
from typing import Dict, List, Type

from services.notification.notifiers.base import AbstractBaseNotifier
from services.notification.notifiers.checks import (
    ChangesChecksNotifier,
    PatchChecksNotifier,
    ProjectChecksNotifier,
)
from services.notification.notifiers.comment import CommentNotifier
from services.notification.notifiers.gitter import GitterNotifier
from services.notification.notifiers.hipchat import HipchatNotifier
from services.notification.notifiers.irc import IRCNotifier
from services.notification.notifiers.slack import SlackNotifier
from services.notification.notifiers.status import (
    ChangesStatusNotifier,
    PatchStatusNotifier,
    ProjectStatusNotifier,
)
from services.notification.notifiers.webhook import WebhookNotifier


def get_all_notifier_classes_mapping() -> Dict[str, Type[AbstractBaseNotifier]]:
    return {
        "gitter": GitterNotifier,
        "hipchat": HipchatNotifier,
        "irc": IRCNotifier,
        "slack": SlackNotifier,
        "webhook": WebhookNotifier,
    }


class StatusType(Enum):
    PATCH = "patch"
    PROJECT = "project"
    CHANGES = "changes"


def get_status_notifier_class(
    status_type: str, class_type: str = "status"
) -> Type[AbstractBaseNotifier]:
    if status_type == StatusType.PATCH.value and class_type == "checks":
        return PatchChecksNotifier
    if status_type == StatusType.PROJECT.value and class_type == "checks":
        return ProjectChecksNotifier
    if status_type == StatusType.CHANGES.value and class_type == "checks":
        return ChangesChecksNotifier
    if status_type == StatusType.PATCH.value and class_type == "status":
        return PatchStatusNotifier
    if status_type == StatusType.PROJECT.value and class_type == "status":
        return ProjectStatusNotifier
    if status_type == StatusType.CHANGES.value and class_type == "status":
        return ChangesStatusNotifier


def get_pull_request_notifiers() -> List[Type[AbstractBaseNotifier]]:
    return [CommentNotifier]
