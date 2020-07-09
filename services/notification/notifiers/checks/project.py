from services.notification.notifiers.base import Comparison
from services.notification.notifiers.checks.base import ChecksNotifier
from typing import Any, Tuple
from services.notification.notifiers.mixins.message import MessageMixin
from services.notification.notifiers.mixins.status import StatusProjectMixin
from database.enums import Notification


class ProjectChecksNotifier(MessageMixin, StatusProjectMixin, ChecksNotifier):

    context = "project"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_project

    async def get_message(self, comparison: Comparison):
        diff = await self.get_diff(comparison)
        pull_dict = comparison.enriched_pull.provider_pull
        return self.create_message(comparison, diff, pull_dict, "checks")

    async def build_payload(self, comparison: Comparison):
        """
            This method build the paylod of the project github checks.

            We only show/add the comment message to the top-level check of a project.
            We do not show/add the message on checks that are used with paths/flags.
        """
        state, summary = self.get_project_status(comparison)
        codecov_link = self.get_codecov_pr_link(comparison)

        should_use_upgrade = self.should_use_upgrade_decoration()
        if should_use_upgrade:
            summary = self.get_upgrade_message()

        flags = self.notifier_yaml_settings.get("flags")
        paths = self.notifier_yaml_settings.get("paths")

        if flags is not None or paths is not None or should_use_upgrade:
            return {
                "state": state,
                "output": {
                    "title": "Codecov Report",
                    "summary": "\n\n".join([codecov_link, summary]),
                },
            }

        message = await self.get_message(comparison)
        return {
            "state": state,
            "output": {
                "title": "Codecov Report",
                "summary": "\n\n".join([codecov_link, summary]),
                "text": "\n".join(message),
            },
        }
