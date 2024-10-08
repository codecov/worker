from database.enums import Notification
from services.notification.notifiers.generics import (
    Comparison,
    RequestsYamlBasedNotifier,
)
from services.urls import get_commit_url, get_graph_url


class SlackNotifier(RequestsYamlBasedNotifier):
    BASE_MESSAGE = " ".join(
        [
            "Coverage for <{head_url}|{owner_username}/{repo_name}>",
            "{comparison_string}on `{head_branch}` is `{head_totals_c}%`",
            "via `<{head_url}|{head_short_commitid}>`",
        ]
    )

    COMPARISON_STRING = (
        "*{compare_message}* `<{compare_url}|{compare_notation}{compare_coverage}%>` "
    )

    @property
    def notification_type(self) -> Notification:
        return Notification.slack

    def build_payload(self, comparison: Comparison) -> dict:
        message = self.generate_message(comparison)
        compare_dict = self.generate_compare_dict(comparison)
        color = "good" if compare_dict["notation"] in ("", "+") else "bad"
        attachments = [
            {
                "fallback": "Commit sunburst attachment",
                "color": color,
                "title": "Commit Sunburst",
                "title_link": get_commit_url(comparison.head.commit),
                "image_url": get_graph_url(
                    comparison.head.commit, "sunburst.svg", size=100
                ),
            }
            for attachment_type in self.notifier_yaml_settings.get("attachments", [])
            if attachment_type == "sunburst"
        ]
        return {
            "text": message,
            "author_name": "Codecov",
            "author_link": get_commit_url(comparison.head.commit),
            "attachments": attachments,
        }
