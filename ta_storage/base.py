from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypedDict, TypeVar

import test_results_parser
from shared.django_apps.reports.models import ReportSession

from services.ta_utils import FlakeInfo


class PRCommentAggResult(TypedDict):
    commit_sha: str
    passed_ct: int
    failed_ct: int
    skipped_ct: int
    flaky_failed_ct: int


T = TypeVar("T")


class PRCommentFailResult(TypedDict, Generic[T]):
    id: T
    computed_name: str
    failure_message: str | None
    duration_seconds: float
    upload_id: int


class TADriver(ABC, Generic[T]):
    def __init__(self, repo_id: int) -> None:
        self.repo_id = repo_id

    @abstractmethod
    def write_testruns(
        self,
        timestamp: int | None,
        commit_sha: str,
        branch_name: str,
        upload_id: int,
        flag_names: list[str],
        framework: str | None,
        testruns: list[test_results_parser.Testrun],
    ) -> None:
        pass

    @abstractmethod
    def write_flakes(self, uploads: list[ReportSession]) -> None:
        pass

    @abstractmethod
    def cache_analytics(self, buckets: list[str], branch: str) -> None:
        pass

    @abstractmethod
    def pr_comment_agg(self, commit_sha: str) -> PRCommentAggResult:
        pass

    @abstractmethod
    def pr_comment_fail(self, commit_sha: str) -> list[PRCommentFailResult[T]]:
        pass

    @abstractmethod
    def get_repo_flakes(
        self, test_ids: tuple[T, ...] | None = None
    ) -> dict[T, FlakeInfo]:
        pass
