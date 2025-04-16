from datetime import UTC
from io import BytesIO
from typing import cast

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


# version number that the cache rollup task will be writing to GCS
# if you're creating a new version of the schema, increment this
VERSION = "1"

# list of schemas, you should leave the old ones here as a reference for now
# old schemas should basically be expired after 60 days, since there would be
# no relevant data included in those files after that amount of time

# so from the time you deprecate an old schema, you only have to keep handling it
# for 60 days
NO_VERSION_POLARS_SCHEMA = [
    ("computed_name", pl.String),
    ("flags", pl.List(pl.String)),
    ("failing_commits", pl.Int64),
    ("last_duration", pl.Float64),
    ("avg_duration", pl.Float64),
    ("pass_count", pl.Int64),
    ("fail_count", pl.Int64),
    ("flaky_fail_count", pl.Int64),
    ("skip_count", pl.Int64),
    ("updated_at", pl.Datetime(time_zone=UTC)),
    ("timestamp_bin", pl.Date()),
]

V1_POLARS_SCHEMA = [
    ("computed_name", pl.String),
    ("testsuite", pl.String),
    ("flags", pl.List(pl.String)),
    ("failing_commits", pl.Int64),
    ("last_duration", pl.Float64),
    ("avg_duration", pl.Float64),
    ("pass_count", pl.Int64),
    ("fail_count", pl.Int64),
    ("flaky_fail_count", pl.Int64),
    ("skip_count", pl.Int64),
    ("updated_at", pl.Datetime(time_zone=UTC)),
    ("timestamp_bin", pl.Date()),
]


def cache_rollups(repoid: int, branch: str | None = None):
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
            "testsuite": summary.testsuite,
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

    df = pl.DataFrame(
        data,
        V1_POLARS_SCHEMA,
        orient="row",
    )
    serialized_table = df.write_ipc(None)

    serialized_table.seek(0)

    storage_service = shared.storage.get_appropriate_storage_service(repoid)
    storage_service.write_file(
        cast(str, settings.GCS_BUCKET_NAME),
        rollup_blob_path(repoid, branch),
        serialized_table,
        metadata={"version": VERSION},
    )
    rollup_size_summary.labels("new").observe(serialized_table.tell())
