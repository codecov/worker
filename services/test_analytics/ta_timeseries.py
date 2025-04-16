from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict

import test_results_parser
from django.db import connections
from django.db.models import Q
from shared.django_apps.ta_timeseries.models import (
    Testrun,
    TestrunBranchSummary,
    TestrunSummary,
)
from shared.django_apps.test_analytics.models import Flake

from services.test_analytics.utils import calc_test_id
from services.test_results import FlakeInfo

LOWER_BOUND_NUM_DAYS = 60


def get_flaky_tests_set(repo_id: int) -> set[bytes]:
    return {
        bytes(test_id)
        for test_id in Flake.objects.filter(repoid=repo_id, end_date__isnull=True)
        .values_list("test_id", flat=True)
        .distinct()
    }


def get_flaky_tests_dict(repo_id: int) -> dict[bytes, FlakeInfo]:
    return {
        bytes(flake.test_id): FlakeInfo(flake.fail_count, flake.count)
        for flake in Flake.objects.filter(repoid=repo_id, end_date__isnull=True)
    }


def insert_testrun(
    timestamp: datetime,
    repo_id: int | None,
    commit_sha: str | None,
    branch: str | None,
    upload_id: int | None,
    flags: list[str] | None,
    parsing_info: test_results_parser.ParsingInfo,
    flaky_test_ids: set[bytes] | None = None,
):
    testruns_to_create = []
    for testrun in parsing_info["testruns"]:
        test_id = calc_test_id(
            testrun["name"], testrun["classname"], testrun["testsuite"]
        )
        outcome = testrun["outcome"]

        if outcome == "error":
            outcome = "failure"

        if outcome == "failure" and flaky_test_ids and test_id in flaky_test_ids:
            outcome = "flaky_failure"

        testruns_to_create.append(
            Testrun(
                timestamp=timestamp,
                test_id=test_id,
                name=testrun["name"],
                classname=testrun["classname"],
                testsuite=testrun["testsuite"],
                computed_name=testrun["computed_name"]
                or f"{testrun['classname']}::{testrun['name']}",
                outcome=outcome,
                duration_seconds=testrun["duration"],
                failure_message=testrun["failure_message"],
                framework=parsing_info["framework"],
                filename=testrun["filename"],
                repo_id=repo_id,
                commit_sha=commit_sha,
                branch=branch,
                flags=flags,
                upload_id=upload_id,
            )
        )
    Testrun.objects.bulk_create(testruns_to_create)


class TestInstance(TypedDict):
    test_id: bytes
    computed_name: str
    failure_message: str
    upload_id: int
    duration_seconds: float | None


def get_pr_comment_failures(repo_id: int, commit_sha: str) -> list[TestInstance]:
    with connections["ta_timeseries"].cursor() as cursor:
        cursor.execute(
            """
            SELECT 
                test_id,
                LAST(computed_name, timestamp) as computed_name,
                LAST(failure_message, timestamp) as failure_message,
                LAST(upload_id, timestamp) as upload_id,
                LAST(duration_seconds, timestamp) as duration_seconds
            FROM ta_timeseries_testrun
            WHERE repo_id = %s AND commit_sha = %s AND outcome IN ('failure', 'flaky_failure')
            GROUP BY test_id
            """,
            [repo_id, commit_sha],
        )
        return [
            {
                "test_id": bytes(test_id),
                "computed_name": computed_name,
                "failure_message": failure_message,
                "upload_id": upload_id,
                "duration_seconds": duration_seconds,
            }
            for test_id, computed_name, failure_message, upload_id, duration_seconds in cursor.fetchall()
        ]


class PRCommentAgg(TypedDict):
    passed: int
    failed: int
    skipped: int


def get_pr_comment_agg(repo_id: int, commit_sha: str) -> PRCommentAgg:
    with connections["ta_timeseries"].cursor() as cursor:
        cursor.execute(
            """
            SELECT outcome, count(*) FROM (
                SELECT 
                    test_id,
                    LAST(outcome, timestamp) as outcome
                FROM ta_timeseries_testrun
                WHERE repo_id = %s AND commit_sha = %s
                GROUP BY test_id
            ) AS t
            GROUP BY outcome
            """,
            [repo_id, commit_sha],
        )
        outcome_dict = {outcome: count for outcome, count in cursor.fetchall()}

        return {
            "passed": outcome_dict.get("pass", 0),
            "failed": outcome_dict.get("failure", 0)
            + outcome_dict.get("flaky_failure", 0),
            "skipped": outcome_dict.get("skip", 0),
        }


def get_testruns_for_flake_detection(
    upload_id: int,
    flaky_test_ids: set[bytes],
) -> list[Testrun]:
    return list(
        Testrun.objects.filter(
            Q(upload_id=upload_id)
            & (
                Q(outcome="failure")
                | Q(outcome="flaky_failure")
                | (Q(outcome="pass") & Q(test_id__in=flaky_test_ids))
            )
        )
    )


def update_testrun_to_flaky(timestamp: datetime, test_id: bytes):
    with connections["ta_timeseries"].cursor() as cursor:
        cursor.execute(
            "UPDATE ta_timeseries_testrun SET outcome = %s WHERE timestamp = %s AND test_id = %s",
            ["flaky_failure", timestamp, test_id],
        )


def timestamp_lower_bound():
    return datetime.now() - timedelta(days=LOWER_BOUND_NUM_DAYS)


def get_summary(repo_id: int) -> list[TestrunSummary]:
    return list(
        TestrunSummary.objects.filter(
            repo_id=repo_id, timestamp_bin__gte=timestamp_lower_bound()
        )
    )


def get_branch_summary(repo_id: int, branch: str) -> list[TestrunBranchSummary]:
    return list(
        TestrunBranchSummary.objects.filter(
            repo_id=repo_id, branch=branch, timestamp_bin__gte=timestamp_lower_bound()
        )
    )


@dataclass
class BranchSummary:
    testsuite: str
    classname: str
    name: str
    timestamp_bin: datetime
    computed_name: str
    failing_commits: int
    last_duration_seconds: float
    avg_duration_seconds: float
    pass_count: int
    fail_count: int
    skip_count: int
    flaky_fail_count: int
    updated_at: datetime
    flags: list[str]


def get_testrun_branch_summary_via_testrun(
    repo_id: int, branch: str
) -> list[BranchSummary]:
    with connections["ta_timeseries"].cursor() as cursor:
        cursor.execute(
            """
            select
                testsuite,
                classname,
                name,
                time_bucket(interval '1 days', timestamp) as timestamp_bin,

                min(computed_name) as computed_name,
                COUNT(DISTINCT CASE WHEN outcome = 'failure' OR outcome = 'flaky_failure' THEN commit_sha ELSE NULL END) AS failing_commits,
                last(duration_seconds, timestamp) as last_duration_seconds,
                avg(duration_seconds) as avg_duration_seconds,
                COUNT(*) FILTER (WHERE outcome = 'pass') AS pass_count,
                COUNT(*) FILTER (WHERE outcome = 'failure') AS fail_count,
                COUNT(*) FILTER (WHERE outcome = 'skip') AS skip_count,
                COUNT(*) FILTER (WHERE outcome = 'flaky_failure') AS flaky_fail_count,
                MAX(timestamp) AS updated_at,
                array_merge_dedup_agg(flags) as flags
            from ta_timeseries_testrun
            where repo_id = %s and branch = %s and timestamp > %s
            group by
                testsuite, classname, name, timestamp_bin;
            """,
            [repo_id, branch, timestamp_lower_bound()],
        )

        return [
            BranchSummary(
                testsuite=row[0],
                classname=row[1],
                name=row[2],
                timestamp_bin=row[3],
                computed_name=row[4],
                failing_commits=row[5],
                last_duration_seconds=row[6],
                avg_duration_seconds=row[7],
                pass_count=row[8],
                fail_count=row[9],
                skip_count=row[10],
                flaky_fail_count=row[11],
                updated_at=row[12],
                flags=row[13] or [],
            )
            for row in cursor.fetchall()
        ]
