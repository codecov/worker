from enum import Enum

class Decoration(Enum):
    standard = "standard"
    upgrade = "upgrade"

class Notification(Enum):
    comment = "comment"
    status = "status"
    slack = "slack"
    webhook = "webhook"
    gitter = "gitter"
    irc = "irc"
    hipchat = "hipchat"
