from enum import Enum


class Decoration(Enum):
    standard = "standard"
    upgrade = "upgrade"
    upload_limit = "upload_limit"


class Notification(Enum):
    comment = "comment"
    status_changes = "status_changes"
    status_patch = "status_patch"
    status_project = "status_project"
    checks_changes = "checks_changes"
    checks_patch = "checks_patch"
    checks_project = "checks_project"
    slack = "slack"
    webhook = "webhook"
    gitter = "gitter"
    irc = "irc"
    hipchat = "hipchat"


class NotificationState(Enum):
    pending = "pending"
    success = "success"
    error = "error"


class CompareCommitState(Enum):
    pending = "pending"
    processed = "processed"
    error = "error"


class CompareCommitError(Enum):
    missing_base_report = "missing_base_report"
    missing_head_report = "missing_head_report"
    provider_client_error = "provider_client_error"


class CommitErrorTypes(Enum):
    class Yaml(Enum):
        INVALID = "invalid"
        CLIENT_ERROR = "client_error"
        UNKNOWN_ERROR = "unknown_error"

    class Bot(Enum):
        UNAUTHENTICATED = "unauthenticated"
        REPO_BOT_INVALID = "repo_bot_invalid"
        OWNER_BOT_INVALID = "owner_bot_invalid"
