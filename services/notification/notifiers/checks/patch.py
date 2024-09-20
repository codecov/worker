from database.enums import Notification
from services.notification.notifiers.base import Comparison
from services.notification.notifiers.checks.base import ChecksNotifier
from services.notification.notifiers.mixins.status import StatusPatchMixin
from services.yaml import read_yaml_field


class PatchChecksNotifier(StatusPatchMixin, ChecksNotifier):
    context = "patch"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_patch

    def build_payload(self, comparison: Comparison):
        """
        This method build the paylod of the patch github checks.

        We only add annotaions to the top-level patch check of a project.
        We do not add annotations on checks that are used with paths/flags
        """
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            return {
                "state": state,
                "output": {
                    "title": "Empty Upload",
                    "summary": message,
                },
            }
        state, message = self.get_patch_status(comparison)
        codecov_link = self.get_codecov_pr_link(comparison)

        title = message

        should_use_upgrade = self.should_use_upgrade_decoration()
        if should_use_upgrade:
            message = self.get_upgrade_message(comparison)
            title = "Codecov Report"

        checks_yaml_field = read_yaml_field(self.current_yaml, ("github_checks",))

        should_annotate = (
            checks_yaml_field.get("annotations", False)
            if checks_yaml_field is not None
            else True
        )

        flags = self.notifier_yaml_settings.get("flags")
        paths = self.notifier_yaml_settings.get("paths")
        if (
            flags is not None
            or paths is not None
            or should_use_upgrade
            or should_annotate is False
        ):
            return {
                "state": state,
                "output": {
                    "title": f"{title}",
                    "summary": "\n\n".join([codecov_link, message]),
                },
            }
        diff = comparison.get_diff(use_original_base=True)
        #  TODO: Look into why the apply diff in get_patch_status is not saving state at this point
        comparison.head.report.apply_diff(diff)
        annotations = self.create_annotations(comparison, diff)

        return {
            "state": state,
            "output": {
                "title": f"{title}",
                "summary": "\n\n".join([codecov_link, message]),
                "annotations": annotations,
            },
        }
