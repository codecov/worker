from dataclasses import dataclass
from covreports.resources import Report

from database.models import Commit, PullRequest


@dataclass
class FullCommit(object):
    commit: Commit
    report: Report


@dataclass
class Comparison(object):
    head: FullCommit
    base: FullCommit
    pull: PullRequest
