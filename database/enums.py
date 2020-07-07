from enum import Enum


class Decoration(Enum):
    standard = "standard"
    upgrade = "upgrade"


class Notification(Enum):
    comment = "comment"
    status_changes = "status_changes"
    status_patch = "status_patch"
    status_project = "status_project"
    slack = "slack"
    webhook = "webhook"
    gitter = "gitter"
    irc = "irc"
    hipchat = "hipchat"


class NotificationState(Enum):
    pending = "pending"
    success = "success"
    error = "error"
