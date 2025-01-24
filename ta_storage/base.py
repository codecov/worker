from __future__ import annotations

from abc import ABC, abstractmethod

import test_results_parser

from database.models.reports import Upload


class TADriver(ABC):
    @abstractmethod
    def write_testruns(
        self,
        timestamp: int,
        repo_id: int,
        commit_sha: str,
        branch_name: str,
        upload: Upload,
        framework: str | None,
        testruns: list[test_results_parser.Testrun],
        flaky_test_set: set[str],
    ):
        pass
