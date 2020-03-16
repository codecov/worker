import logging

from services.notification.changes import get_changes
from services.notification.notifiers.status.base import StatusNotifier

log = logging.getLogger(__name__)


class ChangesStatusNotifier(StatusNotifier):

    """This status analyzes the "unexpected changes" (see services/notification/changes.py
        for a better description) and covered lines within it

    Attributes:
        context (str): The context

    Possible results
        - 'No unexpected coverage changes found.'
        - {0} {1} unexpected coverage changes not visible in diff
        - Unable to determine changes, no report found at pull request base
    """

    context = "changes"

    def is_a_change_worth_noting(self, change):
        if not change.new and not change.deleted:
            # has totals and not -10m => 10h
            t = change.totals
            if t:
                # new missed||partial lines
                return (t.misses + t.partials) > 0
        return False

    async def build_payload(self, comparison):
        pull = comparison.pull
        if self.notifier_yaml_settings.get("base") in ("auto", None, "pr") and pull:
            if not comparison.has_base_report():
                description = (
                    "Unable to determine changes, no report found at pull request base"
                )
                state = "success"
                return {"state": state, "message": description}

        # filter changes
        diff_json = await self.get_diff(comparison)
        changes = get_changes(comparison.base.report, comparison.head.report, diff_json)
        if changes:
            changes = list(filter(self.is_a_change_worth_noting, changes))

        # remove new additions
        if changes:
            lpc = len(changes)
            eng = "files have" if lpc > 1 else "file has"
            description = "{0} {1} unexpected coverage changes not visible in diff".format(
                lpc, eng
            )
            return {
                "state": "success"
                if self.notifier_yaml_settings.get("informational")
                else "failure",
                "message": description,
            }

        description = "No unexpected coverage changes found"
        return {"state": "success", "message": description}
