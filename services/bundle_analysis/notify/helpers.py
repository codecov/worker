from typing import Literal

from shared.django_apps.codecov_auth.models import Service
from shared.yaml import UserYaml

from services.bundle_analysis.notify.types import NotificationType


def is_commit_status_configured(
    yaml: UserYaml, service: Service
) -> None | NotificationType:
    is_status_configured: bool | Literal["informational"] = yaml.read_yaml_field(
        "bundle_analysis", "status", _else="informational"
    )
    is_github = service in (Service.GITHUB, Service.GITHUB_ENTERPRISE)
    if is_status_configured:
        if is_github:
            return NotificationType.GITHUB_COMMIT_CHECK
        return NotificationType.COMMIT_STATUS
    return None


def is_comment_configured(yaml: UserYaml, service: Service) -> None | NotificationType:
    is_comment_configured: dict | bool = yaml.read_yaml_field("comment") is not False
    if is_comment_configured:
        return NotificationType.PR_COMMENT
    return None


def get_notification_types_configured(
    yaml: UserYaml, service: Service
) -> tuple[NotificationType]:
    notification_types = [
        is_commit_status_configured(yaml, service),
        is_comment_configured(yaml, service),
    ]
    return tuple(filter(None, notification_types))


def bytes_readable(self, bytes: int) -> str:
    bytes = abs(bytes)

    if bytes < 1000:
        bytes = round(bytes, 2)
        return f"{bytes} bytes"

    kilobytes = bytes / 1000
    if kilobytes < 1000:
        kilobytes = round(kilobytes, 2)
        return f"{kilobytes}kB"

    megabytes = kilobytes / 1000
    if megabytes < 1000:
        megabytes = round(megabytes, 2)
        return f"{megabytes}MB"

    gigabytes = round(megabytes / 1000, 2)
    return f"{gigabytes}GB"
