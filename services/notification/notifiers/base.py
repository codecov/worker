from typing import Mapping, Any
import logging
from dataclasses import dataclass

from database.models import Repository
from services.notification.types import Comparison

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
    ):
        self.repository = repository
        self.title = title
        self.notifier_yaml_settings = notifier_yaml_settings
        self.site_settings = notifier_site_settings
        self.current_yaml = current_yaml

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
