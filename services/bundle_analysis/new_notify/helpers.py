from typing import Literal

from shared.django_apps.codecov_auth.models import Service
from shared.yaml import UserYaml

from database.models.core import Owner
from services.bundle_analysis.new_notify.types import NotificationType


def is_commit_status_configured(
    yaml: UserYaml, owner: Owner
) -> None | NotificationType:
    """Verifies if we should attempt to send bundle analysis commit status based on given YAML.
    Config field is `bundle_analysis.status` (default: "informational")

    If the user is from GitHub and has an app we can send NotificationType.GITHUB_COMMIT_CHECK.
    """
    is_status_configured: bool | Literal["informational"] = yaml.read_yaml_field(
        "bundle_analysis", "status", _else="informational"
    )
    is_github = Service(owner.service) in (Service.GITHUB, Service.GITHUB_ENTERPRISE)
    owner_has_app = owner.github_app_installations != []
    if is_status_configured:
        if is_github and owner_has_app:
            return NotificationType.GITHUB_COMMIT_CHECK
        return NotificationType.COMMIT_STATUS
    return None


def is_comment_configured(yaml: UserYaml, owner: Owner) -> None | NotificationType:
    """Verifies if we should attempt to send bundle analysis PR comment based on given YAML.
    Config field is `comment` (default: see shared.config)
    """
    is_comment_configured: dict | bool = yaml.read_yaml_field("comment") is not False
    if is_comment_configured:
        return NotificationType.PR_COMMENT
    return None


def get_notification_types_configured(
    yaml: UserYaml, owner: Owner
) -> tuple[NotificationType]:
    """Gets a tuple with all the different bundle analysis notifications that we should attempt to send,
    based on the given YAML"""
    notification_types = [
        is_commit_status_configured(yaml, owner),
        is_comment_configured(yaml, owner),
    ]
    return tuple(filter(None, notification_types))


def bytes_readable(bytes: int) -> str:
    """Converts bytes into human-readable string (up to GB)"""
    value = abs(bytes)
    expoent_index = 0

    while value >= 1000 and expoent_index < 3:
        value /= 1000
        expoent_index += 1

    expoent_str = [" bytes", "kB", "MB", "GB"][expoent_index]
    rounted_value = round(value, 2)
    return f"{rounted_value}{expoent_str}"
