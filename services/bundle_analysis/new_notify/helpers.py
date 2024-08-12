import numbers
from typing import Literal

from shared.bundle_analysis import (
    BundleAnalysisComparison,
)
from shared.django_apps.codecov_auth.models import Service
from shared.torngit.base import TorngitBaseAdapter
from shared.validation.types import BundleThreshold
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


def get_github_app_used(torngit: TorngitBaseAdapter | None) -> int | None:
    if torngit is None:
        return None
    torngit_installation = torngit.data.get("installation")
    selected_installation_id = (
        torngit_installation.get("id") if torngit_installation else None
    )
    return selected_installation_id


def bytes_readable(bytes: int) -> str:
    """Converts bytes into human-readable string (up to GB)"""
    negative = bytes < 0
    value = abs(bytes)
    expoent_index = 0

    while value >= 1000 and expoent_index < 3:
        value /= 1000
        expoent_index += 1

    expoent_str = [" bytes", "kB", "MB", "GB"][expoent_index]
    rounted_value = round(value, 2)
    prefix = "-" if negative else ""
    return f"{prefix}{rounted_value}{expoent_str}"


def to_BundleThreshold(value: int | float | BundleThreshold) -> BundleThreshold:
    # Currently the yaml validator returns the raw values, not the BundleThreshold object
    # Because the changes are not forwards compatible.
    # https://github.com/codecov/engineering-team/issues/2087 is to fix that
    # and then this function can be removed too
    if isinstance(value, BundleThreshold):
        return value
    if isinstance(value, numbers.Integral):
        return BundleThreshold("absolute", value)
    return BundleThreshold("percentage", value)


def is_bundle_change_within_bundle_threshold(
    comparison: BundleAnalysisComparison,
    threshold: BundleThreshold,
    compare_non_negative_numbers: bool = False,
) -> bool:
    if threshold.type == "absolute":
        total_size_delta = (
            abs(comparison.total_size_delta)
            if compare_non_negative_numbers
            else comparison.total_size_delta
        )
        return total_size_delta <= threshold.threshold
    else:
        return comparison.percentage_delta <= threshold.threshold
