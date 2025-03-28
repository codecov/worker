"""Notification system

This packages uses the following services:
  - comparison

"""

import logging
from typing import Iterator, List, Optional, TypedDict

from celery.exceptions import CeleryError, SoftTimeLimitExceeded
from shared.config import get_config
from shared.django_apps.codecov_auth.models import Plan
from shared.helpers.yaml import default_if_true
from shared.plan.constants import TierName
from shared.torngit.base import TorngitBaseAdapter
from shared.yaml import UserYaml

from database.enums import notification_type_status_or_checks
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME, Owner, Repository
from services.comparison import ComparisonProxy
from services.decoration import Decoration
from services.license import is_properly_licensed
from services.notification.commit_notifications import store_notification_results
from services.notification.notifiers import (
    StatusType,
    get_all_notifier_classes_mapping,
    get_pull_request_notifiers,
    get_status_notifier_class,
)
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)
from services.notification.notifiers.checks.checks_with_fallback import (
    ChecksWithFallback,
)
from services.notification.notifiers.codecov_slack_app import CodecovSlackAppNotifier
from services.notification.notifiers.mixins.status import StatusState
from services.yaml import read_yaml_field
from services.yaml.reader import get_components_from_yaml

log = logging.getLogger(__name__)


class IndividualResult(TypedDict):
    notifier: str
    title: str
    result: NotificationResult | None


class NotificationService(object):
    def __init__(
        self,
        repository: Repository,
        current_yaml: UserYaml,
        repository_service: TorngitBaseAdapter,
        decoration_type=Decoration.standard,
        gh_installation_name_to_use: str = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    ) -> None:
        self.repository = repository
        self.current_yaml = current_yaml
        self.decoration_type = decoration_type
        self.repository_service = repository_service
        self.gh_installation_name_to_use = gh_installation_name_to_use
        self.plan = None  # used for caching the plan / tier information

    def _should_use_status_notifier(self, status_type: StatusType) -> bool:
        owner: Owner = self.repository.owner

        if not self.plan:
            self.plan = Plan.objects.select_related("tier").get(name=owner.plan)

        if (
            self.plan.tier.tier_name == TierName.TEAM.value
            and status_type != StatusType.PATCH.value
        ):
            return False

        return True

    def _should_use_checks_notifier(self, status_type: StatusType) -> bool:
        checks_yaml_field = read_yaml_field(self.current_yaml, ("github_checks",))
        if checks_yaml_field is False:
            return False

        owner: Owner = self.repository.owner
        if owner.service not in ["github", "github_enterprise"]:
            return False

        if not self.plan:
            self.plan = Plan.objects.select_related("tier").get(name=owner.plan)

        if (
            self.plan.tier.tier_name == TierName.TEAM.value
            and status_type != StatusType.PATCH.value
        ):
            return False

        app_installation_filter = filter(
            lambda obj: (
                obj.name == self.gh_installation_name_to_use and obj.is_configured()
            ),
            owner.github_app_installations or [],
        )
        # filter is an Iterator, so we need to scan matches
        for app_installation in app_installation_filter:
            if app_installation.is_repo_covered_by_integration(self.repository):
                return True
        # DEPRECATED FLOW
        return (
            self.repository.using_integration
            and self.repository.owner.integration_id
            and (self.repository.owner.service in ["github", "github_enterprise"])
        )

    def _use_status_and_possibly_checks_notifiers(
        self,
        key: StatusType,
        title: str,
        status_config: dict,
    ) -> AbstractBaseNotifier:
        status_notifier_class = get_status_notifier_class(key, "status")
        if self._should_use_checks_notifier(status_type=key):
            checks_notifier = get_status_notifier_class(key, "checks")
            return ChecksWithFallback(
                checks_notifier=checks_notifier(
                    repository=self.repository,
                    title=title,
                    notifier_yaml_settings=status_config,
                    notifier_site_settings={},
                    current_yaml=self.current_yaml,
                    repository_service=self.repository_service,
                    decoration_type=self.decoration_type,
                ),
                status_notifier=status_notifier_class(
                    repository=self.repository,
                    title=title,
                    notifier_yaml_settings=status_config,
                    notifier_site_settings={},
                    current_yaml=self.current_yaml,
                    repository_service=self.repository_service,
                    decoration_type=self.decoration_type,
                ),
            )
        else:
            return status_notifier_class(
                repository=self.repository,
                title=title,
                notifier_yaml_settings=status_config,
                notifier_site_settings={},
                current_yaml=self.current_yaml,
                repository_service=self.repository_service,
                decoration_type=self.decoration_type,
            )

    def get_notifiers_instances(self) -> Iterator[AbstractBaseNotifier]:
        mapping = get_all_notifier_classes_mapping()
        yaml_field = read_yaml_field(self.current_yaml, ("coverage", "notify"))
        if yaml_field is not None:
            for instance_type, instance_configs in yaml_field.items():
                class_to_use = mapping.get(instance_type)
                if not class_to_use:
                    continue
                for title, individual_config in instance_configs.items():
                    yield class_to_use(
                        repository=self.repository,
                        title=title,
                        notifier_yaml_settings=individual_config,
                        notifier_site_settings=get_config(
                            "services", "notifications", instance_type, default=True
                        ),
                        current_yaml=self.current_yaml,
                        repository_service=self.repository_service,
                        decoration_type=self.decoration_type,
                    )

        current_flags = [rf.flag_name for rf in self.repository.flags if not rf.deleted]
        for key, title, status_config in self.get_statuses(current_flags):
            if self._should_use_status_notifier(status_type=key):
                yield self._use_status_and_possibly_checks_notifiers(
                    key=key,
                    title=title,
                    status_config=status_config,
                )

        # yield notifier if slack_app field is True, nonexistent, or a non-empty dict
        slack_app_yaml_field = get_config(
            "setup", "slack_app", default=True
        ) and read_yaml_field(self.current_yaml, ("slack_app",), True)
        if slack_app_yaml_field:
            yield CodecovSlackAppNotifier(
                repository=self.repository,
                title="codecov-slack-app",
                notifier_yaml_settings=slack_app_yaml_field,
                notifier_site_settings={},
                current_yaml=self.current_yaml,
                repository_service=self.repository_service,
                decoration_type=self.decoration_type,
            )

        comment_yaml_field = read_yaml_field(self.current_yaml, ("comment",))
        if comment_yaml_field:
            for pull_notifier_class in get_pull_request_notifiers():
                yield pull_notifier_class(
                    repository=self.repository,
                    title="comment",
                    notifier_yaml_settings=comment_yaml_field,
                    notifier_site_settings={},
                    current_yaml=self.current_yaml,
                    repository_service=self.repository_service,
                    decoration_type=self.decoration_type,
                )

    def _get_component_statuses(self, current_flags: List[str]):
        all_components = get_components_from_yaml(self.current_yaml)
        for component in all_components:
            for status in component.statuses:
                if not status.get(
                    "enabled", True
                ):  # All defined statuses enabled by default
                    continue
                n_st = {
                    "flags": component.get_matching_flags(current_flags),
                    "paths": component.paths,
                    **status,
                }
                yield (
                    status["type"],
                    f"{status.get('name_prefix', '')}{component.get_display_name()}",
                    n_st,
                )

    def get_statuses(self, current_flags: List[str]):
        status_fields = read_yaml_field(self.current_yaml, ("coverage", "status"))
        # Default statuses
        if status_fields:
            for key, value in status_fields.items():
                if key in ["patch", "project", "changes"]:
                    for title, status_config in default_if_true(value):
                        yield (key, title, status_config)
        # Flag based statuses
        for f_name in current_flags:
            flag_configuration = self.current_yaml.get_flag_configuration(f_name)
            if flag_configuration and flag_configuration.get("enabled", True):
                for st in flag_configuration.get("statuses", []):
                    n_st = {"flags": [f_name], **st}
                    yield (st["type"], f"{st.get('name_prefix', '')}{f_name}", n_st)
        # Component based statuses
        for component_status in self._get_component_statuses(current_flags):
            yield component_status

    def notify(self, comparison: ComparisonProxy) -> list[IndividualResult]:
        if not is_properly_licensed(comparison.head.commit.get_db_session()):
            log.warning(
                "Not sending notifications because the system is not properly licensed"
            )
            return []
        log.debug(
            f"Notifying with decoration type {self.decoration_type}",
            extra=dict(
                head_commit=comparison.head.commit.commitid,
                base_commit=(
                    comparison.project_coverage_base.commit.commitid
                    if comparison.project_coverage_base.commit is not None
                    else "NO_BASE"
                ),
                repoid=comparison.head.commit.repoid,
            ),
        )

        status_or_checks_notifiers, all_other_notifiers = split_notifiers(
            notifier
            for notifier in self.get_notifiers_instances()
            if notifier.is_enabled()
        )

        results = [
            self.notify_individual_notifier(notifier, comparison)
            for notifier in status_or_checks_notifiers
        ]

        status_or_checks_helper_text = {}
        if results and all_other_notifiers:
            # if the status/check fails, sometimes we want to add helper text to the message of the other notifications,
            # to better surface that the status/check failed.
            # so if there are status_and_checks_notifiers and all_other_notifiers, do the status_and_checks_notifiers first,
            # look at the results of the checks, if any failed AND they are the type we have helper text for,
            # add that text onto the other notifiers messages through status_or_checks_helper_text.
            for _notifier, result in results:
                if result is not None and result.data_sent is not None:
                    if (
                        result.data_sent.get("state") == StatusState.failure.value
                    ) and result.data_sent.get("included_helper_text"):
                        status_or_checks_helper_text.update(
                            result.data_sent["included_helper_text"]
                        )

        results.extend(
            self.notify_individual_notifier(
                notifier,
                comparison,
                status_or_checks_helper_text=status_or_checks_helper_text,
            )
            for notifier in all_other_notifiers
        )

        store_notification_results(comparison, results)

        return [
            IndividualResult(
                notifier=notifier.name, title=notifier.title, result=result
            )
            for notifier, result in results
        ]

    def notify_individual_notifier(
        self,
        notifier: AbstractBaseNotifier,
        comparison: ComparisonProxy,
        status_or_checks_helper_text: Optional[dict[str, str]] = None,
    ) -> tuple[AbstractBaseNotifier, NotificationResult | None]:
        commit = comparison.head.commit
        base_commit = comparison.project_coverage_base.commit
        log_extra = {
            "commit": commit.commitid,
            "base_commit": base_commit.commitid
            if base_commit is not None
            else "NO_BASE",
            "repoid": commit.repoid,
            "notifier": notifier.name,
            "notifier_title": notifier.title,
        }

        log.info("Attempting individual notification", extra=log_extra)
        try:
            res = notifier.notify(
                comparison, status_or_checks_helper_text=status_or_checks_helper_text
            )
            log_extra["result"] = res

            # TODO: The `CommentNotifier` is the only one implementing this method,
            # so maybe we should just move it there
            notifier.store_results(comparison, res)

            log.info("Individual notification done", extra=log_extra)
            return notifier, res
        except (CeleryError, SoftTimeLimitExceeded):
            raise
        except Exception:
            log.exception("Individual notifier failed", extra=log_extra)
            return notifier, None


def split_notifiers(
    notifiers: Iterator[AbstractBaseNotifier],
) -> tuple[list[AbstractBaseNotifier], list[AbstractBaseNotifier]]:
    "Splits the input notifiers based on whether they are a status/check, or other notifier."

    status_or_checks_notifiers = []
    all_other_notifiers = []

    for notifier in notifiers:
        if notifier.notification_type in notification_type_status_or_checks:
            status_or_checks_notifiers.append(notifier)
        else:
            all_other_notifiers.append(notifier)

    return status_or_checks_notifiers, all_other_notifiers
