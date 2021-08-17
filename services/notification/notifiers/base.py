import logging
from dataclasses import dataclass
from typing import Any, Mapping

from database.models import Repository
from services.comparison.types import Comparison
from services.decoration import Decoration

log = logging.getLogger(__name__)


@dataclass
class NotificationResult(object):
    notification_attempted: bool
    notification_successful: bool
    explanation: str
    data_sent: Mapping[str, Any]
    data_received: Mapping[str, Any] = None


class AbstractBaseNotifier(object):
    """
        Base Notifier, abstract class that should not be used

        This class has the core ideas of a notifier that has the structure:

        notifications:
            <notifier_name:
                <notifier_title>:
                    ... <notifier_fields>
                    
    """

    def __init__(
        self,
        repository: Repository,
        title: str,
        notifier_yaml_settings: Mapping[str, Any],
        notifier_site_settings: Mapping[str, Any],
        current_yaml: Mapping[str, Any],
        decoration_type: Decoration = None,
    ):
        """
            :param repository: The repository notifications are being sent to.
            :param title: The project name for this notification, if applicable. For more info see https://docs.codecov.io/docs/commit-status#splitting-up-projects-example
            :param notifier_yaml_settings: Contains the codecov yaml fields, if any, for this particular notification.
                example: status -> patch -> custom_project_name -> <whatever is here is in notifier_yaml_settings for custom_project_name's status patch notifier>
            :param notifier_site_settings -> Contains the codecov yaml fields under the "notify" header
            :param current_yaml -> The complete codecov yaml used for this notification.
            :param decoration_type -> Indicates whether the user needs to upgrade their account before they can see the notification
        """
        self.repository = repository
        self.title = title
        self.notifier_yaml_settings = notifier_yaml_settings
        self.site_settings = notifier_site_settings
        self.current_yaml = current_yaml
        self.decoration_type = decoration_type

    @property
    def name(self) -> str:
        raise NotImplementedError()

    async def notify(self, comparison: Comparison, **extra_data) -> NotificationResult:
        raise NotImplementedError()

    def is_enabled(self) -> bool:
        raise NotImplementedError()

    def store_results(self, comparison: Comparison, result: NotificationResult):
        """
            This function stores the result in the notification wherever it needs to be saved
            This is the only function in this class allowed to have side-effects in the database

        Args:
            comparison (Comparison): The comparison with which this notify ran
            result (NotificationResult): The results of the notificaiton
        """
        raise NotImplementedError()

    def should_use_upgrade_decoration(self) -> bool:
        return self.decoration_type == Decoration.upgrade
