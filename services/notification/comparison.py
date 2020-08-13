from typing import List, Optional

from shared.reports.types import Change


from services.repository import get_repo_provider_service
from services.notification.changes import get_changes
from services.notification.types import Comparison


class ComparisonProxy(object):

    """The idea of this class is to produce a wrapper around Comparison with functionalities that
        are useful to the notifications context.

        What ComparisonProxy aims to do is to provide a bunch of common calculations (like
            get_changes and get_diff) with a specific set of assumptions very fit for the
            notification use-cases (like the one that we should use the head commit repository
            to fetch data, or that there is even a repository we can fetch data from,
            and that whatever information is fetched at first would not change).

        This is not really meant for other places where a comparison might be used (
            like when one really only needs the actual in-database and in-report information).
            A pure Comparison should be used for those cases

    Attributes:
        comparison (Comparison): The original comparison we want to wrap and proxy
    """

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

    async def get_changes(self) -> Optional[List[Change]]:
        if self._changes is None:
            diff = await self.get_diff()
            self._changes = get_changes(
                self.comparison.base.report, self.comparison.head.report, diff
            )
        return self._changes
