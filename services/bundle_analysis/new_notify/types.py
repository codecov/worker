from enum import Enum


class NotificationType(Enum):
    PR_COMMENT = "pr_comment"
    COMMIT_STATUS = "commit_status"
    # See docs on the difference between COMMIT_STATUS and GITHUB_COMMIT_CHECK
    # https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks#types-of-status-checks-on-github
    GITHUB_COMMIT_CHECK = "github_commit_check"
