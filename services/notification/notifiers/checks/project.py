from services.notification.notifiers.base import Comparison
from services.notification.notifiers.checks.base import ChecksNotifier
from typing import Any, Tuple
from services.notification.notifiers.mixins.message import MessageMixin
from services.notification.notifiers.mixins.status import StatusProjectMixin
from database.enums import Notification
from services.yaml.reader import read_yaml_field


class ProjectChecksNotifier(MessageMixin, StatusProjectMixin, ChecksNotifier):

    context = "project"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_project

    async def get_message(self, comparison: Comparison, yaml_comment_settings):
        diff = await self.get_diff(comparison)
        pull_dict = comparison.enriched_pull.provider_pull
        return self.create_message(comparison, diff, pull_dict, yaml_comment_settings)

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
            summary = self.get_upgrade_message(comparison)

        flags = self.notifier_yaml_settings.get("flags")
        paths = self.notifier_yaml_settings.get("paths")
        yaml_comment_settings = read_yaml_field(self.current_yaml, ("comment",)) or {}
        if "flag" in yaml_comment_settings.get("layout", ""):
            old_flags_list = yaml_comment_settings.get("layout", "").split(",")
            new_flags_list = [x for x in old_flags_list if "flag" not in x]
            yaml_comment_settings["layout"] = ",".join(new_flags_list)

        if (
            flags is not None
            or paths is not None
            or should_use_upgrade
            or not yaml_comment_settings
        ):
            return {
                "state": state,
                "output": {
                    "title": "Codecov Report",
                    "summary": "\n\n".join([codecov_link, summary]),
                },
            }

        message = await self.get_message(comparison, yaml_comment_settings)
        return {
            "state": state,
            "output": {
                "title": "Codecov Report",
                "summary": "\n\n".join([codecov_link, summary]),
                "text": "\n".join(message),
            },
        }
