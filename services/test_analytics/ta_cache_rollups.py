from datetime import UTC
from io import BytesIO

import polars as pl
import shared.storage

from django_scaffold import settings
from services.test_analytics.ta_metrics import (
    read_rollups_from_db_summary,
    rollup_size_summary,
)
from services.test_analytics.ta_timeseries import (
    get_branch_summary,
    get_summary,
    get_testrun_branch_summary_via_testrun,
)


def rollup_blob_path(repoid: int, branch: str | None = None) -> str:
    return (
        f"test_analytics/branch_rollups/{repoid}/{branch}.arrow"
        if branch
        else f"test_analytics/repo_rollups/{repoid}.arrow"
    )


POLARS_SCHEMA = [
    "computed_name",
    ("flags", pl.List(pl.String)),
    "failing_commits",
    "last_duration",
    "avg_duration",
    "pass_count",
    "fail_count",
    "flaky_fail_count",
    "skip_count",
    ("updated_at", pl.Datetime(time_zone=UTC)),
    "timestamp_bin",
]


def cache_rollups(repoid: int, branch: str | None = None):
    storage_service = shared.storage.get_appropriate_storage_service(repoid)
    serialized_table: BytesIO

    with read_rollups_from_db_summary.labels("new").time():
        if branch:
            if branch in {"main", "master", "develop"}:
                summaries = get_branch_summary(repoid, branch)
            else:
                summaries = get_testrun_branch_summary_via_testrun(repoid, branch)
        else:
            summaries = get_summary(repoid)

    data = [
        {
            "computed_name": summary.computed_name,
            "flags": summary.flags,
            "failing_commits": summary.failing_commits,
            "last_duration": summary.last_duration_seconds,
            "avg_duration": summary.avg_duration_seconds,
            "pass_count": summary.pass_count,
            "fail_count": summary.fail_count,
            "flaky_fail_count": summary.flaky_fail_count,
            "skip_count": summary.skip_count,
            "updated_at": summary.updated_at,
            "timestamp_bin": summary.timestamp_bin.date(),
        }
        for summary in summaries
    ]

    serialized_table = pl.DataFrame(
        data,
        POLARS_SCHEMA,
        orient="row",
    ).write_ipc(None)

    serialized_table.seek(0)

    storage_service.write_file(
        settings.GCS_BUCKET_NAME, rollup_blob_path(repoid, branch), serialized_table
    )
    rollup_size_summary.labels("new").observe(serialized_table.tell())
