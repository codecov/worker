from dataclasses import dataclass
from covreports.resources import Report

from database.models import Commit, Pull


@dataclass
class FullCommit(object):
    commit: Commit
    report: Report


@dataclass
class Comparison(object):
    head: FullCommit
    base: FullCommit
    pull: Pull

    def has_base_report(self):
        return bool(self.base is not None and self.base.report is not None)
