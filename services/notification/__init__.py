import logging
import dataclasses
from typing import List

from covreports.config import get_config
from covreports.helpers.yaml import default_if_true
from helpers.metrics import metrics
from services.notification.notifiers import (
    get_all_notifier_classes_mapping, get_status_notifier_class, get_pull_request_notifiers
)
from services.notification.types import Comparison
from services.notification.notifiers.base import NotificationResult
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


class NotificationService(object):

    def __init__(self, repository, current_yaml):
        self.repository = repository
        self.current_yaml = current_yaml

    def get_notifiers_instances(self):
        mapping = get_all_notifier_classes_mapping()
        yaml_field = read_yaml_field(self.current_yaml, ('coverage', 'notify'))
        if yaml_field is not None:
            for instance_type, instance_configs in yaml_field.items():
                class_to_use = mapping.get(instance_type)
                for title, individual_config in instance_configs.items():
                    yield class_to_use(
                        repository=self.repository,
                        title=title,
                        notifier_yaml_settings=individual_config,
                        notifier_site_settings=get_config('services', 'notifications', instance_type, default=True),
                        current_yaml=self.current_yaml
                    )
        status_fields = read_yaml_field(self.current_yaml, ('coverage', 'status'))
        if status_fields:
            for key, value in status_fields.items():
                if key in ['patch', 'project', 'changes']:
                    for title, status_config in default_if_true(value):
                        notifier_class = get_status_notifier_class(key)
                        yield notifier_class(
                            repository=self.repository,
                            title=title,
                            notifier_yaml_settings=status_config,
                            notifier_site_settings={},
                            current_yaml=self.current_yaml
                        )
                else:
                    log.warning(
                        "User has unexpected status type",
                        extra=dict(
                            repoid=self.repository.repoid,
                            current_yaml=self.current_yaml
                        )
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
                )

    async def notify(self, comparison: Comparison) -> List[NotificationResult]:
        notifications = []
        commit = comparison.head.commit
        base_commit = comparison.base.commit
        for notifier in self.get_notifiers_instances():
            if notifier.is_enabled():
                log.info(
                    "Attempting individual notification",
                    extra=dict(
                        commit=commit.commitid,
                        base_commit=base_commit.commitid if base_commit is not None else 'NO_BASE',
                        repoid=commit.repoid,
                        notifier=notifier.name,
                        notifier_title=notifier.title
                    )
                )
                try:
                    with metrics.timer(f'new_worker.services.notifications.notifiers.{notifier.name}'):
                        res = await notifier.notify(comparison)
                    individual_result = {
                        'notifier': notifier.name,
                        'title': notifier.title,
                        'result': dataclasses.asdict(res)
                    }
                    notifier.store_results(comparison, res)
                    notifications.append(individual_result)
                    log.info(
                        "Individual notification done",
                        extra=dict(
                            individual_result=individual_result,
                            commit=commit.commitid,
                            base_commit=base_commit.commitid if base_commit is not None else 'NO_BASE',
                            repoid=commit.repoid
                        )
                    )
                except Exception:
                    individual_result = {
                        'notifier': notifier.name,
                        'title': notifier.title,
                        'result': None
                    }
                    notifications.append(individual_result)
                    log.exception(
                        "Individual notifier failed",
                        extra=dict(
                            repoid=commit.repoid,
                            commit=commit.commitid,
                            individual_result=individual_result,
                            base_commit=base_commit.commitid if base_commit is not None else 'NO_BASE',
                        )
                    )
        return notifications
