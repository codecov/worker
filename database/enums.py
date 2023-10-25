from enum import Enum


class Decoration(Enum):
    standard = "standard"
    upgrade = "upgrade"
    upload_limit = "upload_limit"
    passing_empty_upload = "passing_empty_upload"
    failing_empty_upload = "failing_empty_upload"
    processing_upload = "processing_upload"


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
    codecov_slack_app = "codecov_slack_app"


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
    INVALID_YAML = "invalid_yaml"
    YAML_CLIENT_ERROR = "yaml_client_error"
    YAML_UNKNOWN_ERROR = "yaml_unknown_error"
    REPO_BOT_INVALID = "repo_bot_invalid"


class TrialStatus(Enum):
    NOT_STARTED = "not_started"
    ONGOING = "ongoing"
    EXPIRED = "expired"
    CANNOT_TRIAL = "cannot_trial"
