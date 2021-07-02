from dataclasses import dataclass
from shared.reports.resources import Report

from services.repository import EnrichedPull
from database.models import Commit, Pull


@dataclass
class FullCommit(object):
    commit: Commit
    report: Report


@dataclass
class Comparison(object):
    head: FullCommit
    base: FullCommit
    enriched_pull: EnrichedPull

    def has_base_report(self):
        return bool(self.base is not None and self.base.report is not None)

    @property
    def pull(self):
        if self.enriched_pull is None:
            return None
        return self.enriched_pull.database_pull
