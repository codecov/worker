from services.notification.notifiers.base import Comparison
from services.notification.notifiers.checks.base import ChecksNotifier
from typing import Any, Tuple
from services.notification.notifiers.mixins.message import MessageMixin
from services.notification.notifiers.mixins.status import StatusProjectMixin


class ProjectChecksNotifier(MessageMixin, StatusProjectMixin, ChecksNotifier):

    context = "project"

    async def get_message(self, comparison: Comparison):
        diff = await self.get_diff(comparison)
        pull_dict = comparison.enriched_pull.provider_pull
        return self.create_message(comparison, diff, pull_dict, "checks")

    async def build_payload(self, comparison: Comparison):
        state, summary = self.get_project_status(comparison)
        codecov_link = self.get_codecov_pr_link(comparison)
        if self.title != "default":
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
