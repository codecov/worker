from database.enums import Notification
from services.notification.notifiers.base import Comparison
from services.notification.notifiers.checks.base import ChecksNotifier
from services.notification.notifiers.mixins.message import MessageMixin
from services.notification.notifiers.mixins.status import StatusProjectMixin
from services.yaml.reader import read_yaml_field


class ProjectChecksNotifier(MessageMixin, StatusProjectMixin, ChecksNotifier):
    context = "project"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_project

    def get_message(self, comparison: Comparison, yaml_comment_settings):
        pull_dict = comparison.enriched_pull.provider_pull
        return self.create_message(comparison, pull_dict, yaml_comment_settings)

    def build_payload(self, comparison: Comparison):
        """
        This method build the paylod of the project github checks.

        We only show/add the comment message to the top-level check of a project.
        We do not show/add the message on checks that are used with paths/flags.
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

        state, summary = self.get_project_status(comparison)
        codecov_link = self.get_codecov_pr_link(comparison)

        title = summary

        should_use_upgrade = self.should_use_upgrade_decoration()
        if should_use_upgrade:
            summary = self.get_upgrade_message(comparison)
            title = "Codecov Report"
        flags = self.notifier_yaml_settings.get("flags")
        paths = self.notifier_yaml_settings.get("paths")
        yaml_comment_settings = read_yaml_field(self.current_yaml, ("comment",)) or {}
        if yaml_comment_settings is True:
            yaml_comment_settings = self.site_settings.get("comment", {})
        # copying to a new variable because we will be modifying that
        settings_to_be_used = dict(yaml_comment_settings)
        if "flag" in settings_to_be_used.get("layout", ""):
            old_flags_list = settings_to_be_used.get("layout", "").split(",")
            new_flags_list = [x for x in old_flags_list if "flag" not in x]
            settings_to_be_used["layout"] = ",".join(new_flags_list)

        if (
            flags is not None
            or paths is not None
            or should_use_upgrade
            or not settings_to_be_used
        ):
            return {
                "state": state,
                "output": {
                    "title": f"{title}",
                    "summary": "\n\n".join([codecov_link, summary]),
                },
            }

        message = self.get_message(comparison, settings_to_be_used)
        return {
            "state": state,
            "output": {
                "title": f"{title}",
                "summary": "\n\n".join([codecov_link, summary]),
                "text": "\n".join(message),
            },
        }
