from services.notification.notifiers.base import Comparison
from services.notification.notifiers.checks.base import ChecksNotifier
from services.notification.notifiers.mixins.status import StatusPatchMixin


class PatchChecksNotifier(StatusPatchMixin, ChecksNotifier):

    context = "patch"

    async def build_payload(self, comparison: Comparison):
        state, message = await self.get_patch_status(comparison)
        codecov_link = self.get_codecov_pr_link(comparison)
        if self.title != "default":
            return {
                "state": state,
                "output": {
                    "title": "Codecov Report",
                    "summary": "\n\n".join([codecov_link, message]),
                },
            }
        diff = await self.get_diff(comparison)
        annotations = self.create_annotations(comparison, diff)
        return {
            "state": state,
            "output": {
                "title": "Codecov Report",
                "summary": "\n\n".join([codecov_link, message]),
                "annotations": annotations,
            },
        }
