from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

import test_results_parser
from google.cloud.bigquery import ArrayQueryParameter, ScalarQueryParameter
from shared.config import get_config

import generated_proto.testrun.ta_testrun_pb2 as ta_testrun_pb2
from database.models.reports import Upload
from services.bigquery import get_bigquery_service
from ta_storage.base import TADriver
from ta_storage.utils import calc_flags_hash, calc_test_id

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
    flags
FROM
    latest_instances
WHERE
    outcome = 1
"""

TESTRUNS_FOR_UPLOAD = """
SELECT
    DATE_BUCKET(timestamp, INTERVAL 1 DAY) AS date,
    test_id,
    outcome,
    branch_name,
FROM
    `{PROJECT_ID}.{DATASET_NAME}.{TESTRUN_TABLE_NAME}`
WHERE
    upload_id = @upload_id
    AND (
        outcome = 1
        OR outcome = 3
        OR test_id IN UNNEST(@test_ids)
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


class BQDriver(TADriver):
    def __init__(self, flaky_test_set: set[bytes] | None = None):
        self.flaky_test_set = flaky_test_set or {}
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

    def write_testruns(
        self,
        timestamp: int | None,
        repo_id: int,
        commit_sha: str,
        branch_name: str,
        upload: Upload,
        framework: str | None,
        testruns: list[test_results_parser.Testrun],
    ):
        if timestamp is None:
            timestamp = int(datetime.now().timestamp() * 1000000)

        flag_names: list[str] = upload.flag_names
        testruns_pb: list[bytes] = []

        flags_hash = calc_flags_hash(flag_names)

        for t in testruns:
            test_id = calc_test_id(t["name"], t["classname"], t["testsuite"])
            if test_id in self.flaky_test_set and t["outcome"] == "failure":
                outcome = ta_testrun_pb2.TestRun.Outcome.FLAKY_FAILED
            else:
                outcome = outcome_to_enum(t["outcome"])

            test_run = ta_testrun_pb2.TestRun(
                timestamp=timestamp,
                repoid=repo_id,
                commit_sha=commit_sha,
                framework=framework,
                branch_name=branch_name,
                flags=list(flag_names),
                classname=t["classname"],
                name=t["name"],
                testsuite=t["testsuite"],
                computed_name=t["computed_name"],
                outcome=outcome,
                failure_message=t["failure_message"],
                duration_seconds=t["duration"],
                filename=t["filename"],
                upload_id=upload.id_,
                flags_hash=flags_hash,
                test_id=test_id,
            )
            testruns_pb.append(test_run.SerializeToString())

        self.bq_service.write(
            self.dataset_name, self.testrun_table_name, ta_testrun_pb2, testruns_pb
        )

    def pr_comment_agg(
        self,
        repoid: int,
        commit_sha: str,
    ):
        query = f"""
        WITH 
        {RANKED_DATA.format(
            PROJECT_ID=self.project_id,
            DATASET_NAME=self.dataset_name,
            TESTRUN_TABLE_NAME=self.testrun_table_name,
        )},
        {LATEST_INSTANCES}
        {PR_COMMENT_AGG}
        """
        return self.bq_service.query(
            query,
            [
                ScalarQueryParameter("repoid", "INT64", repoid),
                ScalarQueryParameter("commit_sha", "STRING", commit_sha),
            ],
        )

    def pr_comment_fail(self, repoid: int, commit_sha: str):
        query = f"""
        WITH 
        {RANKED_DATA.format(
            PROJECT_ID=self.project_id,
            DATASET_NAME=self.dataset_name,
            TESTRUN_TABLE_NAME=self.testrun_table_name,
        )},
        {LATEST_INSTANCES}
        {PR_COMMENT_FAIL}
        """
        return self.bq_service.query(
            query,
            [
                ScalarQueryParameter("repoid", "INT64", repoid),
                ScalarQueryParameter("commit_sha", "STRING", commit_sha),
            ],
        )

    def testruns_for_upload(self, upload_id: int, test_ids: list[bytes]):
        query = f"""
        {TESTRUNS_FOR_UPLOAD.format(
            PROJECT_ID=self.project_id,
            DATASET_NAME=self.dataset_name,
            TESTRUN_TABLE_NAME=self.testrun_table_name,
        )}
        """
        return self.bq_service.query(
            query,
            [
                ScalarQueryParameter("upload_id", "INT64", upload_id),
                ArrayQueryParameter("test_ids", "BYTES", test_ids),
            ],
        )

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
            {ANALYTICS_BRANCH.format(
                PROJECT_ID=self.project_id,
                DATASET_NAME=self.dataset_name,
                TESTRUN_TABLE_NAME=self.testrun_table_name,
            )}
            {ANALYTICS}
            """
        else:
            query = f"""
            WITH
            {ANALYTICS_BASE.format(
                PROJECT_ID=self.project_id,
                DATASET_NAME=self.dataset_name,
                TESTRUN_TABLE_NAME=self.testrun_table_name,
            )}
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
