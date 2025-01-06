from abc import ABC, abstractmethod
from typing import Any

from database.models.reports import Upload


class TADriver(ABC):
    @abstractmethod
    def write_testruns(
        self,
        repo_id: int,
        commit_id: str,
        branch: str,
        upload: Upload,
        framework: str | None,
        testruns: list[dict[str, Any]],
    ):
        pass
