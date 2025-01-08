from abc import ABC, abstractmethod

from test_results_parser import Testrun

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
        testruns: list[Testrun],
    ):
        pass
