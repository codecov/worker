from torngit.enums import Endpoints

from services.notification.notifiers.generics import RequestsYamlBasedNotifier, Comparison
from services.urls import get_commit_url


class GitterNotifier(RequestsYamlBasedNotifier):

    # TODO (Thiago): Fix base message
    BASE_MESSAGE = " ".join([
        "Coverage for <{head_url}|{owner_username}/{repo_name}>",
        "{comparison_string}on `{head_branch}` is `{head_totals_c}%`",
        "via `<{head_url}|{head_short_commitid}>`"
    ])

    COMPARISON_STRING = "*{compare_message}* {compare_notation}{compare_coverage}% "

    def build_payload(self, comparison: Comparison):
        compare_dict = self.generate_compare_dict(comparison)
        message = self.generate_message(comparison)
        head_commit = comparison.head.commit
        return {
            "message": message,
            "branch": head_commit.branch,
            "pr": comparison.pull.pullid if comparison.pull else None,
            "commit": head_commit.commitid,
            "commit_short": head_commit.commitid[:7],
            "text": compare_dict['message'],
            "commit_url": self.repository_service.get_href(
                Endpoints.commit_detail, commitid=head_commit.commitid
            ),
            "codecov_url": get_commit_url(head_commit),
            "coverage": comparison.head.report.totals.coverage,
            "coverage_change": compare_dict['coverage']
        }
