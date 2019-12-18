from typing import Mapping, Any
import logging

from database.models import Repository
from services.notification.types import Comparison

log = logging.getLogger(__name__)


class AbstractBaseNotifier(object):
    """
        Base Notifier, abstract class that should not be used

        This class has the core ideas of a notifier that has the structure:

        notifications:
            <notifier_name:
                <notifier_title>:
                    ... <notifier_fields>

        The only real piece of logic on this class is that it checks whether
            this notifier is enabled on the site-wide settings
    """

    def __init__(self, repository: Repository, title: str, notifier_yaml_settings: Mapping[str, Any], notifier_site_settings: Mapping[str, Any], current_yaml: Mapping[str, Any]):
        self.repository = repository
        self.title = title
        self.notifier_yaml_settings = notifier_yaml_settings
        self.site_settings = notifier_site_settings
        self.current_yaml = current_yaml

    @property
    def name(self) -> str:
        raise NotImplementedError()

    async def notify(self, comparison: Comparison, **extra_data) -> dict:
        raise NotImplementedError()

    def is_enabled(self) -> bool:
        raise NotImplementedError()
