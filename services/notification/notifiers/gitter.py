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
        return {
            "message": message,
            "branch": comparison.head.commit.branch,
            "pr": comparison.pull.pullid if comparison.pull else None,
            "commit": comparison.head.commit.commitid,
            "commit_short": comparison.head.commit.commitid[:7],
            "text": compare_dict['message'],
            # TODO (Thiago): Implement with get_href
            "commit_url": None,
            "codecov_url": get_commit_url(comparison.head.commit),
            "coverage": comparison.head.report.totals.coverage,
            "coverage_change": compare_dict['coverage']
        }
