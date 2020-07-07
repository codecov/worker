import logging
import dataclasses
from typing import List
import asyncio
import os
from celery.exceptions import CeleryError, SoftTimeLimitExceeded

from shared.config import get_config
from shared.helpers.yaml import default_if_true
from helpers.metrics import metrics
from services.decoration import Decoration
from services.notification.notifiers import (
    get_all_notifier_classes_mapping,
    get_status_notifier_class,
    get_pull_request_notifiers,
)
from services.notification.types import Comparison
from services.notification.notifiers.base import (
    NotificationResult,
    AbstractBaseNotifier,
)
from services.commit_notifications import (
    create_or_update_commit_notification_from_notification_result,
)
from services.yaml import read_yaml_field
from services.license import is_properly_licensed
from typing import Any, Iterator

log = logging.getLogger(__name__)


class NotificationService(object):
    def __init__(
        self, repository, current_yaml, decoration_type=Decoration.standard
    ) -> None:
        self.repository = repository
        self.current_yaml = current_yaml
        self.decoration_type = decoration_type

    def get_notifiers_instances(self) -> Iterator[AbstractBaseNotifier]:
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
                        decoration_type=self.decoration_type,
                    )
        status_fields = read_yaml_field(self.current_yaml, ("coverage", "status"))
        if status_fields:
            whitelisted_ownerids = os.getenv("CHECKS_WHITELISTED_OWNERS", "").split(",")
            whitelisted_ownerids = [
                int(ownerid.strip())
                for ownerid in whitelisted_ownerids
                if ownerid != ""
            ]
            for key, value in status_fields.items():
                if key in ["patch", "project", "changes"]:
                    for title, status_config in default_if_true(value):
                        notifier_class_type = "status"
                        if (
                            self.repository.using_integration
                            and self.repository.owner.integration_id
                            and (
                                self.repository.owner.service == "github"
                                or self.repository.owner.service == "github_enterprise"
                            )
                            and self.repository.owner.ownerid in whitelisted_ownerids
                        ):
                            checks_yaml_field = read_yaml_field(
                                self.current_yaml, ("github_checks",)
                            )
                            if checks_yaml_field is not False:
                                notifier_class_type = "checks"
                        notifier_class = get_status_notifier_class(
                            key, notifier_class_type
                        )
                        yield notifier_class(
                            repository=self.repository,
                            title=title,
                            notifier_yaml_settings=status_config,
                            notifier_site_settings={},
                            current_yaml=self.current_yaml,
                            decoration_type=self.decoration_type,
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
                    decoration_type=self.decoration_type,
                )

    async def notify(self, comparison: Comparison) -> List[NotificationResult]:
        if not is_properly_licensed(comparison.head.commit.get_db_session()):
            log.warning(
                "Not sending notifications because the system is not properly licensed"
            )
            return []
        log.info(
            f"Notifying with decoration type {self.decoration_type}",
            extra=dict(
                head_commit=comparison.head.commit.commitid,
                base_commit=comparison.base.commit.commitid
                if comparison.base.commit is not None
                else "NO_BASE",
                repoid=comparison.head.commit.repoid,
            ),
        )
        notification_tasks = []
        for notifier in self.get_notifiers_instances():
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
                f"worker.services.notifications.notifiers.{notifier.name}"
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
            individual_result = {
                "notifier": notifier.name,
                "title": notifier.title,
                "result": None,
            }
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
        except asyncio.CancelledError:
            log.warning(
                "Individual notifier cancelled",
                extra=dict(repoid=commit.repoid, commit=commit.commitid,),
            )
            individual_result = {
                "notifier": notifier.name,
                "title": notifier.title,
                "result": None,
            }
            raise
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
        finally:
            create_or_update_commit_notification_from_notification_result(
                comparison.pull, notifier, individual_result["result"]
            )
