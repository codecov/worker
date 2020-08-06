from services.repository import get_repo_provider_service
from services.notification.changes import get_changes
from services.notification.types import Comparison


class ComparisonProxy(object):
    def __init__(self, comparison: Comparison):
        self.comparison = comparison
        self._repository_service = None
        self._diff = None
        self._changes = None

    @property
    def repository_service(self):
        if self._repository_service is None:
            self._repository_service = get_repo_provider_service(
                self.comparison.head.commit.repository
            )
        return self._repository_service

    def has_base_report(self):
        return self.comparison.has_base_report()

    @property
    def head(self):
        return self.comparison.head

    @property
    def base(self):
        return self.comparison.base

    @property
    def enriched_pull(self):
        return self.comparison.enriched_pull

    @property
    def pull(self):
        return self.comparison.pull

    async def get_diff(self):
        if self._diff is None:
            head = self.comparison.head.commit
            base = self.comparison.base.commit
            if base is None:
                return None
            pull_diff = await self.repository_service.get_compare(
                base.commitid, head.commitid, with_commits=False
            )
            self._diff = pull_diff["diff"]
        return self._diff

    async def get_changes(self):
        if self._changes is None:
            diff = await self.get_diff()
            self._changes = get_changes(
                self.comparison.base.report, self.comparison.head.report, diff
            )
        return self._changes
