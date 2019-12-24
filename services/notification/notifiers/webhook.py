import logging

from services.notification.notifiers.generics import RequestsYamlBasedNotifier
from services.notification.types import FullCommit, Comparison
from services.urls import get_commit_url, get_repository_url

log = logging.getLogger(__name__)


def build_commit_payload(full_commit: FullCommit):
    if full_commit.commit is None:
        return None
    commit = full_commit.commit
    return {
        "author": {
            "username": commit.author.username,
            "service_id": commit.author.service_id,
            "email": commit.author.email,
            "service": commit.author.service,
            "name": commit.author.name
        },
        "url": get_commit_url(commit),
        "timestamp": commit.timestamp.isoformat(),
        "totals": full_commit.report.totals._asdict() if full_commit.report is not None else None,
        "commitid": commit.commitid,
        # TODO (Thiago): Implement get_href on torngit
        "service_url": f"https://{commit.repository.service}.com/{commit.repository.slug}/commit/{commit.commitid}",
        "branch": commit.branch,
        "message": commit.message
    }


class WebhookNotifier(RequestsYamlBasedNotifier):

    def build_payload(self, comparison: Comparison):
        head_full_commit = comparison.head
        base_full_commit = comparison.base
        pull = comparison.pull
        head_commit = head_full_commit.commit
        repository = head_commit.repository
        pull_dict = None
        if pull:
            pull_dict = {
                "head": {
                    "commit": pull.head,
                    "branch": "master"
                },
                "number": str(pull.pullid),
                "base": {
                    "commit": pull.base,
                    "branch": "master"
                },
                "open": pull.state == 'open',
                "id": pull.pullid,
                "merged": pull.state == 'merged'
            }
        return {
            "repo": {
                "url": get_repository_url(head_commit.repository),
                "service_id": repository.service_id,
                "name": repository.name,
                "private": repository.private
            },
            "head": build_commit_payload(head_full_commit),
            "base": build_commit_payload(base_full_commit),
            "compare": self.generate_compare_dict(comparison),
            "owner": {
                "username": repository.owner.username,
                "service_id": repository.owner.service_id,
                "service": repository.owner.service
            },
            "pull": pull_dict
        }
