import pytest
from shared.reports.resources import Report

from database.tests.factories.core import CommitFactory
from services.comparison.types import FullCommit


@pytest.mark.parametrize(
    "full_commit, expected",
    [
        (
            FullCommit(commit=None, report=None),
            "FullCommit<commit=NO_COMMIT, has_report=False>",
        ),
        (
            FullCommit(commit=CommitFactory(commitid="123abcSHA1"), report=None),
            "FullCommit<commit=123abcSHA1, has_report=False>",
        ),
        (
            FullCommit(commit=CommitFactory(commitid="123abcSHA1"), report=Report()),
            "FullCommit<commit=123abcSHA1, has_report=True>",
        ),
        (
            FullCommit(commit=None, report=Report()),
            "FullCommit<commit=NO_COMMIT, has_report=True>",
        ),
    ],
)
def test_FullCommit_repr(full_commit, expected):
    assert str(full_commit) == expected
