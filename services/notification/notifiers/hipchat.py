from decimal import Decimal

from database.enums import Notification
from services.notification.notifiers.generics import (
    Comparison,
    RequestsYamlBasedNotifier,
)
from services.urls import get_commit_url, get_graph_url
from services.yaml.reader import round_number


class HipchatNotifier(RequestsYamlBasedNotifier):
    # TODO (Thiago): Fix base message
    BASE_MESSAGE = " ".join(
        [
            'Coverage for <a href="{head_url}">{owner_username}/{repo_name}</a>',
            "{comparison_string}on <code>{head_branch}</code> is <code>{head_totals_c}%</code>",
            '# via <a href="{head_url}">{head_short_commitid}</a>',
        ]
    )

    COMPARISON_STRING = "<strong>{compare_message}</strong> <code>{compare_notation}{compare_coverage}%</code> "

    @property
    def notification_type(self) -> Notification:
        return Notification.hipchat

    def build_payload(self, comparison: Comparison) -> dict:
        card = None
        head_commit = comparison.head.commit
        commitid = head_commit.commitid
        repository = comparison.head.commit.repository
        head_url = get_commit_url(comparison.head.commit)
        comparison_dict = self.generate_compare_dict(comparison)
        if self.notifier_yaml_settings.get("card"):
            compare = []
            if comparison.project_coverage_base.report is not None:
                compare = [
                    {
                        "label": "Compare",
                        "value": {
                            "style": {"+": "lozenge-success", "-": "lozenge-error"}.get(
                                comparison_dict["notation"], "lozenge-current"
                            ),
                            "label": "{0}{1}%".format(
                                comparison_dict["notation"],
                                round_number(
                                    self.current_yaml, comparison_dict["coverage"]
                                ),
                            ),
                        },
                    }
                ]
            card = {
                "id": commitid,
                "title": f"Codecov \u22c5 {repository.slug} on {head_commit.branch}",
                "style": "application",
                "format": "compact",
                "url": head_url,
                "icon": {
                    "url": get_graph_url(
                        comparison.head.commit, "sunburst.svg", size=100
                    )
                },
                "attributes": [
                    {
                        "label": "Author",
                        "value": {
                            "url": head_url,
                            "label": comparison.head.commit.author.username,
                        },
                    },
                    {
                        "label": "Commit",
                        "value": {"url": head_url, "label": commitid[:7]},
                    },
                ]
                + compare,
                "description": {
                    "value": "Coverage for {0} on {1} is now {2}%".format(
                        repository.slug,
                        head_commit.branch,
                        round_number(
                            self.current_yaml,
                            Decimal(comparison.head.report.totals.coverage),
                        ),
                    ),
                    "format": "html",
                },
            }
        message = self.generate_message(comparison)
        return {
            "from": "Codecov",
            "card": card,
            "message": message,
            "color": {"+": "green", "-": "red"}.get(
                comparison_dict["notation"], "gray"
            ),
            "notify": self.notifier_yaml_settings.get("notify", False),
            "message_format": "html",
        }
