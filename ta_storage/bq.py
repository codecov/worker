from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

import test_results_parser
from shared.config import get_config

import generated_proto.testrun.ta_testrun_pb2 as ta_testrun_pb2
from database.models.reports import Upload
from services.bigquery import get_bigquery_service
from ta_storage.base import TADriver

DATASET_NAME: str = cast(
    str, get_config("services", "bigquery", "dataset_name", default="codecov_prod")
)

TESTRUN_TABLE_NAME: str = cast(
    str, get_config("services", "bigquery", "testrun_table_name", default="testruns")
)


def outcome_to_int(
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
        bq_service = get_bigquery_service()

        if timestamp is None:
            timestamp = int(datetime.now().timestamp() * 1000000)

        flag_names = upload.flag_names
        testruns_pb: list[bytes] = []

        for t in testruns:
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
                outcome=outcome_to_int(t["outcome"]),
                failure_message=t["failure_message"],
                duration_seconds=t["duration"],
                filename=t["filename"],
            )
            testruns_pb.append(test_run.SerializeToString())
        flag_names = upload.flag_names

        bq_service.write(DATASET_NAME, TESTRUN_TABLE_NAME, ta_testrun_pb2, testruns_pb)
