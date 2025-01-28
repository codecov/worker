from typing import Optional

from database.enums import Notification
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.checks.base import (
    CheckOutput,
    CheckResult,
    ChecksNotifier,
)
from services.notification.notifiers.mixins.message import MessageMixin
from services.notification.notifiers.mixins.status import StatusProjectMixin
from services.yaml.reader import read_yaml_field


class ProjectChecksNotifier(MessageMixin, StatusProjectMixin, ChecksNotifier):
    context = "project"
    notification_type_display_name = "check"

    @property
    def notification_type(self) -> Notification:
        return Notification.checks_project

    def get_message(
        self,
        comparison: ComparisonProxy | FilteredComparison,
        yaml_comment_settings,
        status_or_checks_helper_text: Optional[dict[str, str]] = None,
    ):
        pull_dict = comparison.enriched_pull.provider_pull
        return self.create_message(
            comparison,
            pull_dict,
            yaml_comment_settings,
            status_or_checks_helper_text=status_or_checks_helper_text,
        )

    def build_payload(
        self, comparison: ComparisonProxy | FilteredComparison
    ) -> CheckResult:
        """
        This method build the paylod of the project github checks.

        We only show/add the comment message to the top-level check of a project.
        We do not show/add the message on checks that are used with paths/flags.
        """
        if self.is_empty_upload():
            state, message = self.get_status_check_for_empty_upload()
            result = CheckResult(
                state=state,
                output=CheckOutput(
                    title="Empty Upload", summary=message, annotations=[]
                ),
                included_helper_text={},
            )
            return result

        status_result = self.get_project_status(
            comparison, notification_type=self.notification_type_display_name
        )
        codecov_link = self.get_codecov_pr_link(comparison)

        title = status_result["message"]
        summary = status_result["message"]

        should_use_upgrade = self.should_use_upgrade_decoration()
        if should_use_upgrade:
            title = "Codecov Report"
            summary = self.get_upgrade_message(comparison)

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
            result = CheckResult(
                state=status_result["state"],
                output=CheckOutput(
                    title=title,
                    summary="\n\n".join([codecov_link, summary]),
                    annotations=[],
                ),
                included_helper_text=status_result["included_helper_text"],
            )
            return result

        message = self.get_message(
            comparison,
            settings_to_be_used,
            status_or_checks_helper_text=status_result["included_helper_text"],
        )
        result = CheckResult(
            state=status_result["state"],
            output=CheckOutput(
                title=title,
                summary="\n\n".join([codecov_link, summary]),
                annotations=[],
                text="\n".join(message),
            ),
            included_helper_text=status_result["included_helper_text"],
        )
        return result
