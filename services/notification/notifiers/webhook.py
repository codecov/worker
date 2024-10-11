import logging

from shared.torngit.enums import Endpoints

from database.enums import Notification
from services.comparison.types import Comparison, FullCommit
from services.notification.notifiers.generics import RequestsYamlBasedNotifier
from services.urls import get_commit_url, get_repository_url

log = logging.getLogger(__name__)


class WebhookNotifier(RequestsYamlBasedNotifier):
    @property
    def notification_type(self) -> Notification:
        return Notification.webhook

    def build_commit_payload(self, full_commit: FullCommit):
        if full_commit.commit is None:
            return None
        commit = full_commit.commit
        author_dict = None
        if commit.author is not None:
            author_dict = {
                "username": commit.author.username,
                "service_id": commit.author.service_id,
                "email": commit.author.email,
                "service": commit.author.service,
                "name": commit.author.name,
            }
        return {
            "author": author_dict,
            "url": get_commit_url(commit),
            "timestamp": commit.timestamp.isoformat(),
            "totals": full_commit.report.totals.asdict()
            if full_commit.report is not None
            else None,
            "commitid": commit.commitid,
            "service_url": self.repository_service.get_href(
                Endpoints.commit_detail, commitid=commit.commitid
            ),
            "branch": commit.branch,
            "message": commit.message,
        }

    def build_payload(self, comparison: Comparison) -> dict:
        head_full_commit = comparison.head
        base_full_commit = comparison.project_coverage_base
        pull = comparison.pull
        head_commit = head_full_commit.commit
        repository = head_commit.repository
        pull_dict = None
        if pull:
            pull_dict = {
                "head": {"commit": pull.head, "branch": "master"},
                "number": str(pull.pullid),
                "base": {"commit": pull.base, "branch": "master"},
                "open": pull.state == "open",
                "id": pull.pullid,
                "merged": pull.state == "merged",
            }
        return {
            "repo": {
                "url": get_repository_url(head_commit.repository),
                "service_id": repository.service_id,
                "name": repository.name,
                "private": repository.private,
            },
            "head": self.build_commit_payload(head_full_commit),
            "base": self.build_commit_payload(base_full_commit),
            "compare": self.generate_compare_dict(comparison),
            "owner": {
                "username": repository.owner.username,
                "service_id": repository.owner.service_id,
                "service": repository.owner.service,
            },
            "pull": pull_dict,
        }
