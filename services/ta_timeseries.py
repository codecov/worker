from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import TypedDict

import test_results_parser
from django.db import connections
from django.db.models import Q
from shared.django_apps.test_analytics.models import Flake
from shared.django_apps.timeseries.models import (
    Testrun,
    TestrunBranchSummary,
    TestrunSummary,
)

from services.test_results import FlakeInfo
from ta_storage.utils import calc_flags_hash, calc_test_id


class Interval(Enum):
    ONE_DAY = 1
    SEVEN_DAYS = 7
    THIRTY_DAYS = 30


def get_flaky_tests_set(repo_id: int) -> set[bytes]:
    return set(
        Flake.objects.filter(repoid=repo_id, end_date__isnull=True)
        .values_list("test_id", flat=True)
        .distinct()
    )


def get_flaky_tests_dict(repo_id: int) -> dict[bytes, FlakeInfo]:
    return {
        flake.test_id: FlakeInfo(flake.fail_count, flake.count)
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
        flags_hash = calc_flags_hash(flags) if flags else None
        outcome = testrun["outcome"]

        if outcome == "failure" and flaky_test_ids and test_id in flaky_test_ids:
            outcome = "flaky_failure"

        testruns_to_create.append(
            Testrun(
                timestamp=timestamp,
                test_id=test_id,
                flags_hash=flags_hash,
                name=testrun["name"],
                classname=testrun["classname"],
                testsuite=testrun["testsuite"],
                computed_name=testrun["computed_name"],
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
    flags_hash: bytes | None
    computed_name: str
    failure_message: str
    upload_id: int
    duration_seconds: float | None


def get_pr_comment_failures(repo_id: int, commit_sha: str) -> list[TestInstance]:
    with connections["timeseries"].cursor() as cursor:
        cursor.execute(
            """
            SELECT 
                test_id,
                flags_hash,
                LAST(computed_name, timestamp) as computed_name,
                LAST(failure_message, timestamp) as failure_message,
                LAST(upload_id, timestamp) as upload_id,
                LAST(duration_seconds, timestamp) as duration_seconds
            FROM timeseries_testrun
            WHERE repo_id = %s AND commit_sha = %s AND outcome IN ('failure', 'flaky_failure')
            GROUP BY test_id, flags_hash
            """,
            [repo_id, commit_sha],
        )
        return [
            {
                "test_id": bytes(test_id),
                "flags_hash": bytes(flags_hash),
                "computed_name": computed_name,
                "failure_message": failure_message,
                "upload_id": upload_id,
                "duration_seconds": duration_seconds,
            }
            for test_id, flags_hash, computed_name, failure_message, upload_id, duration_seconds in cursor.fetchall()
        ]


def get_pr_comment_agg(repo_id: int, commit_sha: str) -> dict[str, int]:
    with connections["timeseries"].cursor() as cursor:
        cursor.execute(
            """
            SELECT outcome, count(*) FROM (
                SELECT 
                    test_id,
                    flags_hash,
                    LAST(outcome, timestamp) as outcome
                FROM timeseries_testrun
                WHERE repo_id = %s AND commit_sha = %s
                GROUP BY test_id, flags_hash
            ) AS t
            GROUP BY outcome
            """,
            [repo_id, commit_sha],
        )
        return {outcome: count for outcome, count in cursor.fetchall()}


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


def update_testrun_to_flaky(
    timestamp: datetime, test_id: bytes, flags_hash: bytes | None
):
    with connections["timeseries"].cursor() as cursor:
        cursor.execute(
            "UPDATE timeseries_testrun SET outcome = %s WHERE timestamp = %s AND test_id = %s AND flags_hash = %s",
            ["flaky_failure", timestamp, test_id, flags_hash],
        )


def get_testrun_summary(
    repo_id: int, interval: Interval, branch: str | None = None
) -> list[TestrunSummary]:
    timestamp_bin = datetime.now() - timedelta(days=interval.value)
    return list(
        TestrunSummary.objects.filter(repo_id=repo_id, timestamp_bin__gte=timestamp_bin)
    )


def get_testrun_branch_summary(
    repo_id: int, branch: str, interval: Interval
) -> list[TestrunBranchSummary]:
    timestamp_bin = datetime.now() - timedelta(days=interval.value)
    return list(
        TestrunBranchSummary.objects.filter(
            repo_id=repo_id, branch=branch, timestamp_bin__gte=timestamp_bin
        )
    )
