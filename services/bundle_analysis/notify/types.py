from dataclasses import dataclass
from enum import Enum
from typing import Literal

from shared.validation.types import BundleThreshold


class NotificationType(Enum):
    PR_COMMENT = "pr_comment"
    COMMIT_STATUS = "commit_status"
    # See docs on the difference between COMMIT_STATUS and GITHUB_COMMIT_CHECK
    # https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks#types-of-status-checks-on-github
    GITHUB_COMMIT_CHECK = "github_commit_check"


class NotificationSuccess(Enum):
    ALL_ERRORED = "all_processing_results_errored"
    NOTHING_TO_NOTIFY = "nothing_to_notify"
    FULL_SUCCESS = "full_success"
    PARTIAL_SUCCESS = "partial_success"


@dataclass
class NotificationUserConfig:
    warning_threshold: BundleThreshold
    status_level: bool | Literal["informational"]
    required_changes: bool | Literal["bundle_increase"]
    required_changes_threshold: BundleThreshold
