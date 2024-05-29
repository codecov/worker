from unittest.mock import MagicMock

import pytest
from shared.reports.resources import Report
from shared.utils.sessions import Session, SessionType

from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, FullCommit, ReportUploadedCount


@pytest.mark.parametrize(
    "head_sessions, base_sessions, expected_count, expected_diff",
    [
        (
            [
                Session(
                    flags=["unit", "local"], session_type=SessionType.carriedforward
                ),
                Session(flags=["integration"], session_type=SessionType.uploaded),
                Session(flags=["unit"], session_type=SessionType.uploaded),
                Session(flags=["unit"], session_type=SessionType.uploaded),
                Session(flags=["integration"], session_type=SessionType.uploaded),
                Session(flags=[], session_type=SessionType.uploaded),
            ],
            [
                Session(
                    flags=["unit", "local"], session_type=SessionType.carriedforward
                ),
                Session(flags=["integration"], session_type=SessionType.carriedforward),
                Session(flags=["unit"], session_type=SessionType.uploaded),
                Session(flags=["unit"], session_type=SessionType.uploaded),
            ],
            [
                ReportUploadedCount(flag="unit", base_count=2, head_count=2),
                ReportUploadedCount(flag="integration", base_count=0, head_count=2),
                ReportUploadedCount(flag="", base_count=0, head_count=1),
            ],
            [],
        ),
        (
            [
                Session(
                    flags=["unit", "local"], session_type=SessionType.carriedforward
                ),
                Session(flags=["integration"], session_type=SessionType.uploaded),
                Session(flags=["unit"], session_type=SessionType.uploaded),
                Session(flags=["unit"], session_type=SessionType.uploaded),
                Session(flags=["integration"], session_type=SessionType.uploaded),
                Session(flags=[""], session_type=SessionType.uploaded),
            ],
            [
                Session(flags=["unit", "local"], session_type=SessionType.uploaded),
                Session(flags=["integration"], session_type=SessionType.uploaded),
                Session(flags=["unit"], session_type=SessionType.uploaded),
                Session(flags=["unit"], session_type=SessionType.uploaded),
                Session(flags=["obscure_flag"], session_type=SessionType.uploaded),
            ],
            [
                ReportUploadedCount(flag="unit", base_count=3, head_count=2),
                ReportUploadedCount(flag="local", base_count=1, head_count=0),
                ReportUploadedCount(flag="integration", base_count=1, head_count=2),
                ReportUploadedCount(flag="obscure_flag", base_count=1, head_count=0),
                ReportUploadedCount(flag="", base_count=0, head_count=1),
            ],
            [
                ReportUploadedCount(flag="unit", base_count=3, head_count=2),
                ReportUploadedCount(flag="integration", base_count=1, head_count=2),
            ],
        ),
    ],
    ids=["flag_counts_no_diff", "flag_count_yes_diff"],
)
def test_get_reports_uploaded_count_per_flag(
    head_sessions, base_sessions, expected_count, expected_diff
):
    head_report = Report()
    head_report.sessions = head_sessions
    base_report = Report()
    base_report.sessions = base_sessions
    comparison_proxy = ComparisonProxy(
        comparison=Comparison(
            head=FullCommit(report=head_report, commit=None),
            project_coverage_base=FullCommit(report=base_report, commit=None),
            patch_coverage_base_commitid=None,
            enriched_pull=None,
        )
    )
    # Python Dicts preserve order, so we can actually test this equality
    # See more https://stackoverflow.com/a/39537308
    assert comparison_proxy.get_reports_uploaded_count_per_flag() == expected_count
    assert comparison_proxy.get_reports_uploaded_count_per_flag_diff() == expected_diff


def test_get_reports_uploaded_count_per_flag_cached():
    comparison_proxy = ComparisonProxy(comparison=MagicMock(name="fake_comparison"))
    comparison_proxy._cached_reports_uploaded_per_flag = (
        "object_that_doesnt_have_this_shape"
    )
    assert (
        comparison_proxy.get_reports_uploaded_count_per_flag()
        == "object_that_doesnt_have_this_shape"
    )


def test_get_reports_uploaded_count_per_flag_diff_missing_report():
    head_report = None
    base_report = Report()
    base_report.sessions = None
    comparison_proxy = ComparisonProxy(
        comparison=Comparison(
            head=FullCommit(report=head_report, commit=None),
            project_coverage_base=FullCommit(report=base_report, commit=None),
            patch_coverage_base_commitid=None,
            enriched_pull=None,
        )
    )
    assert comparison_proxy.get_reports_uploaded_count_per_flag_diff() == []
