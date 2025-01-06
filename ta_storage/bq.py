from typing import Any, cast

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


def outcome_to_int(outcome: str) -> int:
    match outcome:
        case "pass":
            return 0
        case "skip":
            return 2
        case "failure" | "error":
            return 1
        case _:
            raise ValueError(f"Invalid outcome: {outcome}")


class BQDriver(TADriver):
    def write_testruns(
        self,
        repo_id: int,
        commit_id: str,
        branch: str,
        upload: Upload,
        framework: str | None,
        testruns: list[dict[str, Any]],
    ):
        bq_service = get_bigquery_service()

        testruns = [
            {k: v for k, v in testrun.items() if k != "build_url"}
            for testrun in testruns
        ]

        for testrun in testruns:
            testrun["outcome"] = outcome_to_int(testrun["outcome"])

        flag_names = upload.flag_names

        testruns_pb: list[bytes] = []
        for testrun in testruns:
            test_run = ta_testrun_pb2.TestRun(
                repoid=repo_id,
                commit_sha=commit_id,
                framework=framework or "",
                branch=branch,
                flags=list(flag_names),
                **testrun,
            )
            print(test_run)
            testruns_pb.append(test_run.SerializeToString())

        bq_service.write(DATASET_NAME, TESTRUN_TABLE_NAME, ta_testrun_pb2, testruns_pb)
