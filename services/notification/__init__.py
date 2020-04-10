import logging
import dataclasses
from typing import List
import asyncio

from celery.exceptions import CeleryError, SoftTimeLimitExceeded

from covreports.config import get_config
from covreports.helpers.yaml import default_if_true
from helpers.metrics import metrics
from services.decoration import Decoration, get_decoration_type_and_reason
from services.notification.notifiers import (
    get_all_notifier_classes_mapping,
    get_status_notifier_class,
    get_pull_request_notifiers,
)
from services.notification.types import Comparison
from services.notification.notifiers.base import NotificationResult
from services.yaml import read_yaml_field
from services.license import is_properly_licensed

log = logging.getLogger(__name__)


class NotificationService(object):
    def __init__(self, repository, current_yaml):
        self.repository = repository
        self.current_yaml = current_yaml

    def get_notifiers_instances(self, decoration_type=Decoration.standard):
        mapping = get_all_notifier_classes_mapping()
        yaml_field = read_yaml_field(self.current_yaml, ("coverage", "notify"))
        if yaml_field is not None:
            for instance_type, instance_configs in yaml_field.items():
                class_to_use = mapping.get(instance_type)
                for title, individual_config in instance_configs.items():
                    yield class_to_use(
                        repository=self.repository,
                        title=title,
                        notifier_yaml_settings=individual_config,
                        notifier_site_settings=get_config(
                            "services", "notifications", instance_type, default=True
                        ),
                        current_yaml=self.current_yaml,
                        decoration_type=decoration_type,
                    )
        status_fields = read_yaml_field(self.current_yaml, ("coverage", "status"))
        if status_fields:
            for key, value in status_fields.items():
                if key in ["patch", "project", "changes"]:
                    for title, status_config in default_if_true(value):
                        notifier_class = get_status_notifier_class(key)
                        yield notifier_class(
                            repository=self.repository,
                            title=title,
                            notifier_yaml_settings=status_config,
                            notifier_site_settings={},
                            current_yaml=self.current_yaml,
                            decoration_type=decoration_type,
                        )
                else:
                    log.warning(
                        "User has unexpected status type",
                        extra=dict(
                            repoid=self.repository.repoid,
                            current_yaml=self.current_yaml,
                        ),
                    )
        comment_yaml_field = read_yaml_field(self.current_yaml, ("comment",))
        if comment_yaml_field:
            for pull_notifier_class in get_pull_request_notifiers():
                yield pull_notifier_class(
                    repository=self.repository,
                    title="comment",
                    notifier_yaml_settings=comment_yaml_field,
                    notifier_site_settings=None,
                    current_yaml=self.current_yaml,
                    decoration_type=decoration_type,
                )

    async def notify(self, comparison: Comparison) -> List[NotificationResult]:
        if not is_properly_licensed(comparison.head.commit.get_db_session()):
            log.warning("Not sending notifications because the system is not properly licensed")
            return []
        decoration_type, reason = get_decoration_type_and_reason(
            Comparison.enriched_pull
        )
        log.info(
            f"Notifying with decoration type {decoration_type}",
            extra=dict(
                commit=commit.commitid,
                base_commit=base_commit.commitid
                if base_commit is not None
                else "NO_BASE",
                repoid=commit.repoid,
                reason=reason,
            ),
        )
        notification_tasks = []
        for notifier in self.get_notifiers_instances(decoration_type):
            if notifier.is_enabled():
                notification_tasks.append(
                    self.notify_individual_notifier(notifier, comparison)
                )
        return await asyncio.gather(*notification_tasks)

    async def notify_individual_notifier(
        self, notifier, comparison
    ) -> NotificationResult:
        commit = comparison.head.commit
        base_commit = comparison.base.commit
        log.info(
            "Attempting individual notification",
            extra=dict(
                commit=commit.commitid,
                base_commit=base_commit.commitid
                if base_commit is not None
                else "NO_BASE",
                repoid=commit.repoid,
                notifier=notifier.name,
                notifier_title=notifier.title,
            ),
        )
        try:
            with metrics.timer(
                f"new_worker.services.notifications.notifiers.{notifier.name}"
            ):
                res = await asyncio.wait_for(notifier.notify(comparison), timeout=30)
            individual_result = {
                "notifier": notifier.name,
                "title": notifier.title,
                "result": dataclasses.asdict(res),
            }
            notifier.store_results(comparison, res)
            log.info(
                "Individual notification done",
                extra=dict(
                    individual_result=individual_result,
                    commit=commit.commitid,
                    base_commit=base_commit.commitid
                    if base_commit is not None
                    else "NO_BASE",
                    repoid=commit.repoid,
                ),
            )
            return individual_result
        except (CeleryError, SoftTimeLimitExceeded):
            raise
        except asyncio.TimeoutError:
            individual_result = {
                "notifier": notifier.name,
                "title": notifier.title,
                "result": None,
            }
            log.warning(
                "Individual notifier timed out",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    individual_result=individual_result,
                    base_commit=base_commit.commitid
                    if base_commit is not None
                    else "NO_BASE",
                ),
            )
            return individual_result
        except Exception:
            individual_result = {
                "notifier": notifier.name,
                "title": notifier.title,
                "result": None,
            }
            log.exception(
                "Individual notifier failed",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    individual_result=individual_result,
                    base_commit=base_commit.commitid
                    if base_commit is not None
                    else "NO_BASE",
                ),
            )
            return individual_result
