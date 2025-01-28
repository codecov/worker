from __future__ import annotations

import datetime as dt
from datetime import datetime
from functools import cached_property
from typing import Literal, TypedDict, cast

import polars as pl
import shared.storage
import test_results_parser
from django.db import transaction
from google.cloud.bigquery import (
    ArrayQueryParameter,
    ScalarQueryParameter,
    StructQueryParameter,
    StructQueryParameterType,
)
from shared.config import get_config
from shared.django_apps.reports.models import ReportSession
from shared.django_apps.test_analytics.models import Flake

import generated_proto.testrun.ta_testrun_pb2 as ta_testrun_pb2
from services.bigquery import get_bigquery_service
from services.ta_utils import FlakeInfo
from ta_storage.base import (
    PRCommentAggResult,
    PRCommentFailResult,
    TADriver,
)
from ta_storage.utils import calc_flags_hash, calc_test_id


def get_live_flakes(repo_id: int) -> list[Flake]:
    return [
        flake
        for flake in Flake.objects.filter(repoid=repo_id, end_date__isnull=True).all()
    ]


RANKED_DATA = """
ranked_data AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY
                name,
                classname,
                testsuite,
                flags_hash
            ORDER BY timestamp DESC
        ) AS row_num
    FROM
        `{PROJECT_ID}.{DATASET_NAME}.{TESTRUN_TABLE_NAME}`
    WHERE
        repoid = @repoid
        AND commit_sha = @commit_sha
)
"""

LATEST_INSTANCES = """
latest_instances AS (
    SELECT
        *
    FROM
        ranked_data
    WHERE
        row_num = 1
)
"""

PR_COMMENT_AGG = """
SELECT
    *
FROM (
    SELECT
        commit_sha,
        outcome
    FROM
        latest_instances
) PIVOT (
    COUNT(*) AS ct
    FOR outcome IN (
        0 as passed,
        1 as failed,
        2 as skipped,
        3 as flaky_failed
    )
)
"""

PR_COMMENT_FAIL = """
SELECT
    computed_name,
    failure_message,
    test_id,
    flags_hash,
    duration_seconds,
    upload_id
FROM
    latest_instances
WHERE
    outcome = 1
"""

TESTRUNS_FOR_UPLOAD = """
SELECT
    timestamp,
    test_id,
    outcome,
    branch_name,
    flags_hash,
FROM
    `{PROJECT_ID}.{DATASET_NAME}.{TESTRUN_TABLE_NAME}`
WHERE
    upload_id = @upload_id
    AND (
        outcome = 1
        OR outcome = 3
        OR EXISTS (
            SELECT 1
                FROM UNNEST(@flake_ids) AS flake_id
            WHERE flake_id.candidate_test_id = test_id
            AND IF(flake_id.candidate_flags_hash IS NULL, flags_hash IS NULL, flake_id.candidate_flags_hash = flags_hash)
        )
    )
"""

ANALYTICS_BASE = """
analytics_base AS (
    SELECT *
    FROM `{PROJECT_ID}.{DATASET_NAME}.{TESTRUN_TABLE_NAME}`
    WHERE repoid = @repoid
        AND timestamp BETWEEN
        (CURRENT_DATE - INTERVAL @interval_start) AND
        (CURRENT_DATE - INTERVAL @interval_end)
)
"""

ANALYTICS_BRANCH = """
analytics_base AS (
    SELECT *
    FROM `{PROJECT_ID}.{DATASET_NAME}.{TESTRUN_TABLE_NAME}`
    WHERE repoid = @repoid
        AND branch_name = @branch
        AND timestamp BETWEEN
        (CURRENT_TIMESTAMP() - INTERVAL @interval_start DAY) AND
        (CURRENT_TIMESTAMP() - INTERVAL @interval_end DAY)
)
"""

ANALYTICS = """
SELECT
    name,
    classname,
    testsuite,
    ANY_VALUE(computed_name) AS computed_name,
    COUNT(DISTINCT IF(outcome = 1 OR outcome = 3, commit_sha, NULL)) AS cwf,
    AVG(duration_seconds) AS avg_duration,
    MAX_BY(duration_seconds, timestamp) AS last_duration,
    SUM(IF(outcome = 0, 1, 0)) AS pass_count,
    SUM(IF(outcome = 1, 1, 0)) AS fail_count,
    SUM(IF(outcome = 2, 1, 0)) AS skip_count,
    SUM(IF(outcome = 3, 1, 0)) AS flaky_fail_count,
    MAX(timestamp) AS updated_at,
    ARRAY_AGG(DISTINCT unnested_flags) AS flags
FROM analytics_base, UNNEST(flags) AS unnested_flags
GROUP BY name, classname, testsuite
"""


class TestrunsForUploadResult(TypedDict):
    timestamp: int
    test_id: bytes
    flags_hash: bytes
    outcome: Literal["passed", "failed", "skipped", "flaky_failed"]
    branch_name: str


def get_storage_key(
    repo_id: int, branch: str | None, interval_start: int, interval_end: int | None
) -> str:
    interval_section = (
        f"{interval_start}"
        if interval_end is None
        else f"{interval_start}_{interval_end}"
    )

    if branch:
        return f"ta_rollups/{repo_id}/{branch}/{interval_section}"
    else:
        return f"ta_rollups/{repo_id}/{interval_section}"


def outcome_to_enum(
    outcome: Literal["pass", "skip", "failure", "error"],
) -> ta_testrun_pb2.TestRun.Outcome:
    match outcome:
        case "pass":
            return ta_testrun_pb2.TestRun.Outcome.PASSED
        case "skip":
            return ta_testrun_pb2.TestRun.Outcome.SKIPPED
        case "failure" | "error":
            return ta_testrun_pb2.TestRun.Outcome.FAILED
        case _:
            raise ValueError(f"Invalid outcome: {outcome}")


class BQDriver(TADriver[tuple[bytes, bytes | None]]):
    def __init__(self, repo_id: int) -> None:
        super().__init__(repo_id)
        self.bq_service = get_bigquery_service()

        self.project_id: str = cast(
            str, get_config("services", "gcp", "project_id", default="codecov-prod")
        )

        self.dataset_name: str = cast(
            str,
            get_config("services", "bigquery", "dataset_name", default="codecov_prod"),
        )

        self.testrun_table_name: str = cast(
            str,
            get_config(
                "services", "bigquery", "testrun_table_name", default="testruns"
            ),
        )

    def get_live_flakes(self, repo_id: int) -> list[Flake]:
        return [
            flake
            for flake in Flake.objects.filter(
                repoid=repo_id, end_date__isnull=True
            ).all()
        ]

    def write_testruns(
        self,
        timestamp: int | None,
        commit_sha: str,
        branch_name: str,
        upload_id: int,
        flag_names: list[str],
        framework: str | None,
        testruns: list[test_results_parser.Testrun],
    ):
        if timestamp is None:
            timestamp = int(datetime.now().timestamp() * 1000000)

        testruns_pb: list[bytes] = []

        flags_hash = calc_flags_hash(flag_names)

        flakes: list[Flake] = list(self.flake_dict.values())
        flake_set = {(flake.test_id, flake.flags_id) for flake in flakes}

        for t in testruns:
            test_id = calc_test_id(t["name"], t["classname"], t["testsuite"])
            if (test_id, flags_hash) in flake_set and t["outcome"] == "failure":
                outcome = ta_testrun_pb2.TestRun.Outcome.FLAKY_FAILED
            else:
                outcome = outcome_to_enum(t["outcome"])

            test_run = ta_testrun_pb2.TestRun(
                timestamp=timestamp,
                repoid=self.repo_id,
                commit_sha=commit_sha,
                framework=framework,
                branch_name=branch_name,
                flags=list(flag_names),
                classname=t["classname"],
                name=t["name"],
                testsuite=t["testsuite"],
                computed_name=t["computed_name"]
                or f"{t['testsuite']}.{t['classname']}.{t['name']}",
                outcome=outcome,
                failure_message=t["failure_message"],
                duration_seconds=t["duration"],
                filename=t["filename"],
                upload_id=upload_id,
                flags_hash=flags_hash,
                test_id=test_id,
            )
            testruns_pb.append(test_run.SerializeToString())

        self.bq_service.write(
            self.dataset_name, self.testrun_table_name, ta_testrun_pb2, testruns_pb
        )

    def pr_comment_agg(self, commit_sha: str) -> PRCommentAggResult:
        query = f"""
        WITH 
        {
            RANKED_DATA.format(
                PROJECT_ID=self.project_id,
                DATASET_NAME=self.dataset_name,
                TESTRUN_TABLE_NAME=self.testrun_table_name,
            )
        },
        {LATEST_INSTANCES}
        {PR_COMMENT_AGG}
        """
        query_result = self.bq_service.query(
            query,
            [
                ScalarQueryParameter("repoid", "INT64", self.repo_id),
                ScalarQueryParameter("commit_sha", "STRING", commit_sha),
            ],
        )

        result = query_result[0]

        return {
            "commit_sha": result["commit_sha"],
            "passed_ct": result["passed"],
            "failed_ct": result["failed"],
            "skipped_ct": result["skipped"],
            "flaky_failed_ct": result["flaky_failed"],
        }

    def pr_comment_fail(
        self, commit_sha: str
    ) -> list[PRCommentFailResult[tuple[bytes, bytes | None]]]:
        query = f"""
        WITH 
        {
            RANKED_DATA.format(
                PROJECT_ID=self.project_id,
                DATASET_NAME=self.dataset_name,
                TESTRUN_TABLE_NAME=self.testrun_table_name,
            )
        },
        {LATEST_INSTANCES}
        {PR_COMMENT_FAIL}
        """
        query_result = self.bq_service.query(
            query,
            [
                ScalarQueryParameter("repoid", "INT64", self.repo_id),
                ScalarQueryParameter("commit_sha", "STRING", commit_sha),
            ],
        )

        return [
            {
                "computed_name": result["computed_name"],
                "failure_message": result["failure_message"],
                "id": (result["test_id"], result["flags_hash"]),
                "duration_seconds": result["duration_seconds"],
                "upload_id": result["upload_id"],
            }
            for result in query_result
        ]

    def testruns_for_upload(
        self, upload_id: int, flake_set: set[tuple[bytes, bytes | None]]
    ) -> list[TestrunsForUploadResult]:
        query = f"""
        {
            TESTRUNS_FOR_UPLOAD.format(
                PROJECT_ID=self.project_id,
                DATASET_NAME=self.dataset_name,
                TESTRUN_TABLE_NAME=self.testrun_table_name,
            )
        }
        """
        # IMPORTANT: the names of these parameters actually matters or
        # else BQ won't be able to disambiguate the test_id of the object
        # up for comparison and the field in the struct
        # if the name of the fields in the structs are equal to the name of the fields
        # in the table, it will match every row
        ids = [
            StructQueryParameter(
                None,
                ScalarQueryParameter("candidate_test_id", "BYTES", test_id),
                ScalarQueryParameter("candidate_flags_hash", "BYTES", flags_hash),
            )
            for (test_id, flags_hash) in flake_set
        ]

        query_result = self.bq_service.query(
            query,
            [
                ScalarQueryParameter("upload_id", "INT64", upload_id),
                ArrayQueryParameter(
                    "flake_ids",
                    StructQueryParameterType(
                        ScalarQueryParameter("candidate_test_id", "BYTES", None),
                        ScalarQueryParameter("candidate_flags_hash", "BYTES", None),
                    ),
                    ids,
                ),
            ],
        )

        return [
            {
                "branch_name": result["branch_name"],
                "timestamp": result["timestamp"],
                "outcome": result["outcome"],
                "test_id": result["test_id"],
                "flags_hash": result["flags_hash"],
            }
            for result in query_result
        ]

    @cached_property
    def flake_dict(self) -> dict[tuple[bytes, bytes | None], Flake]:
        return {
            (
                bytes(flake.test_id),
                bytes(flake.flags_id) if flake.flags_id else None,
            ): flake
            for flake in self.get_live_flakes(self.repo_id)
        }

    def write_flakes(self, uploads: list[ReportSession]) -> None:
        # get relevant flakes test ids:
        flakes = list(self.flake_dict.values())

        flake_dict = {
            (
                bytes(flake.test_id),
                bytes(flake.flags_id) if flake.flags_id else None,
            ): flake
            for flake in flakes
        }

        for upload in uploads:
            testruns = self.testruns_for_upload(upload.id, set(flake_dict.keys()))
            for testrun in testruns:
                if flake := flake_dict.get((testrun["test_id"], testrun["flags_hash"])):
                    match testrun["outcome"]:
                        case (
                            ta_testrun_pb2.TestRun.Outcome.FAILED
                            | ta_testrun_pb2.TestRun.Outcome.FLAKY_FAILED
                        ):
                            flake.fail_count += 1
                            flake.count += 1
                            flake.recent_passes_count = 0
                        case ta_testrun_pb2.TestRun.Outcome.PASSED:
                            flake.recent_passes_count += 1
                            flake.count += 1

                            if flake.recent_passes_count == 30:
                                flake.end_date = datetime.now()
                        case _:
                            pass

                    flake.save()
                else:
                    match testrun["outcome"]:
                        case (
                            ta_testrun_pb2.TestRun.Outcome.FAILED
                            | ta_testrun_pb2.TestRun.Outcome.FLAKY_FAILED
                        ):
                            flake = Flake.objects.create(
                                repoid=self.repo_id,
                                test_id=testrun["test_id"],
                                fail_count=1,
                                count=1,
                                recent_passes_count=0,
                                start_date=datetime.fromtimestamp(
                                    testrun["timestamp"] / 1000000
                                ),
                                end_date=None,
                            )
                            flake.save()

                            flake_dict[(testrun["test_id"], testrun["flags_hash"])] = (
                                flake
                            )
                        case _:
                            pass

            upload.state = "flake_processed"
            upload.save()
            transaction.commit()

    def analytics(
        self,
        repoid: int,
        interval_start: int = 30,  # for convention we want the start to be the larger number of days
        interval_end: int = 0,
        branch: str | None = None,
    ):
        if branch:
            query = f"""
            WITH
            {
                ANALYTICS_BRANCH.format(
                    PROJECT_ID=self.project_id,
                    DATASET_NAME=self.dataset_name,
                    TESTRUN_TABLE_NAME=self.testrun_table_name,
                )
            }
            {ANALYTICS}
            """
        else:
            query = f"""
            WITH
            {
                ANALYTICS_BASE.format(
                    PROJECT_ID=self.project_id,
                    DATASET_NAME=self.dataset_name,
                    TESTRUN_TABLE_NAME=self.testrun_table_name,
                )
            }
            {ANALYTICS}
            """

        params = [
            ScalarQueryParameter("repoid", "INT64", repoid),
            ScalarQueryParameter("interval_start", "INT64", interval_start),
            ScalarQueryParameter("interval_end", "INT64", interval_end),
        ]

        if branch:
            params.append(ScalarQueryParameter("branch", "STRING", branch))

        return self.bq_service.query(query, params)

    def cache_analytics(self, buckets: list[str], branch: str | None) -> None:
        storage_service = shared.storage.get_appropriate_storage_service(self.repo_id)

        for interval_start, interval_end in [
            # NOTE: working with calendar days and intervals,
            # `(CURRENT_DATE - INTERVAL '1 days')` means *yesterday*,
            # and `2..1` matches *the day before yesterday*.
            (1, None),
            (2, 1),
            (7, None),
            (14, 7),
            (30, None),
            (60, 30),
        ]:
            analytics_results = self.analytics(
                self.repo_id,
                interval_start=interval_start,
                interval_end=interval_end,
                branch=branch,
            )

            df = pl.DataFrame(
                analytics_results,
                [
                    "name",
                    "classname",
                    "testsuite",
                    "computed_name",
                    ("flags", pl.List(pl.String)),
                    "test_id",
                    ("updated_at", pl.Datetime(time_zone=dt.UTC)),
                    "avg_duration",
                    "fail_count",
                    "flaky_fail_count",
                    "pass_count",
                    "skip_count",
                    "commits_where_fail",
                    "last_duration",
                ],
                orient="row",
            )

            serialized_table = df.write_ipc(None)
            serialized_table.seek(0)  # avoids Stream must be at beginning errors

            storage_key = get_storage_key(
                self.repo_id, branch, interval_start, interval_end
            )
            for bucket in buckets:
                storage_service.write_file(
                    bucket,
                    storage_key,
                    serialized_table,
                )

    def get_repo_flakes(
        self, test_ids: tuple[tuple[bytes, bytes | None], ...] | None = None
    ) -> dict[tuple[bytes, bytes | None], FlakeInfo]:
        if test_ids:
            return {
                (
                    bytes(flake.test_id),
                    bytes(flake.flags_id) if flake.flags_id else None,
                ): FlakeInfo(
                    failed=flake.fail_count,
                    count=flake.count,
                )
                for flake in Flake.objects.raw(
                    "SELECT * FROM flake WHERE repoid = %s AND (test_id, flags_id) IN %s AND end_date IS NULL AND count != recent_passes_count + fail_count",
                    [self.repo_id, test_ids],
                ).all()
            }
        else:
            return {
                (
                    bytes(flake.test_id),
                    bytes(flake.flags_id) if flake.flags_id else None,
                ): FlakeInfo(
                    failed=flake.fail_count,
                    count=flake.count,
                )
                for flake in Flake.objects.raw(
                    "SELECT * FROM flake WHERE repoid = %s AND end_date IS NULL AND count != recent_passes_count + fail_count",
                    [self.repo_id],
                ).all()
            }
