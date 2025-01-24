from __future__ import annotations

import datetime as dt
from datetime import date, datetime
from typing import Any, Literal, TypedDict

import polars as pl
import shared.storage
import test_results_parser
from django.db import connections
from django.db import transaction as django_transaction
from django.db.models import Q
from shared.config import get_config
from shared.django_apps.reports.models import (
    CommitReport as DjangoCommitReport,
)
from shared.django_apps.reports.models import (
    DailyTestRollup as DjangoDailyTestRollup,
)
from shared.django_apps.reports.models import (
    Flake as DjangoFlake,
)
from shared.django_apps.reports.models import (
    ReportSession as DjangoReportSession,
)
from shared.django_apps.reports.models import (
    TestInstance as DjangoTestInstance,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import (
    DailyTestRollup,
    Flake,
    RepositoryFlag,
    Test,
    TestFlagBridge,
    TestInstance,
)
from services.ta_utils import (
    FlakeInfo,
    generate_flags_hash,
    generate_test_id,
    get_test_summary_for_commit,
    latest_failures_for_commit,
)
from ta_storage.base import (
    PRCommentAggResult,
    PRCommentFailResult,
    TADriver,
)

# Reminder: `a BETWEEN x AND y` is equivalent to `a >= x AND a <= y`
# Since we are working with calendar days, using a range of `0..0` gives us *today*,
# and a range of `1..1` gives use *yesterday*.
BASE_SUBQUERY = """
SELECT *
FROM reports_dailytestrollups
WHERE repoid = %(repoid)s
  AND branch = %(branch)s
  AND date BETWEEN
    (CURRENT_DATE - INTERVAL %(interval_start)s) AND
    (CURRENT_DATE - INTERVAL %(interval_end)s)
"""

TEST_AGGREGATION_SUBQUERY = """
SELECT test_id,
       CASE
           WHEN SUM(pass_count) + SUM(fail_count) = 0 THEN 0
           ELSE SUM(fail_count)::float / (SUM(pass_count) + SUM(fail_count))
       END AS failure_rate,
       CASE
           WHEN SUM(pass_count) + SUM(fail_count) = 0 THEN 0
           ELSE SUM(flaky_fail_count)::float / (SUM(pass_count) + SUM(fail_count))
       END AS flake_rate,
       MAX(latest_run) AS updated_at,
       AVG(avg_duration_seconds) AS avg_duration,
       SUM(fail_count) AS total_fail_count,
       SUM(flaky_fail_count) AS total_flaky_fail_count,
       SUM(pass_count) AS total_pass_count,
       SUM(skip_count) AS total_skip_count
FROM base_cte
GROUP BY test_id
"""

COMMITS_FAILED_SUBQUERY = """
SELECT test_id,
       array_length((array_agg(DISTINCT unnested_cwf)), 1) AS failed_commits_count
FROM
  (SELECT test_id,
          commits_where_fail AS cwf
   FROM base_cte
   WHERE array_length(commits_where_fail, 1) > 0) AS tests_with_commits_that_failed,
     unnest(cwf) AS unnested_cwf
GROUP BY test_id
"""

LAST_DURATION_SUBQUERY = """
SELECT base_cte.test_id,
       last_duration_seconds
FROM base_cte
JOIN
  (SELECT test_id,
          max(created_at) AS created_at
   FROM base_cte
   GROUP BY test_id) AS latest_rollups ON base_cte.created_at = latest_rollups.created_at
AND base_cte.test_id = latest_rollups.test_id
"""

TEST_FLAGS_SUBQUERY = """
SELECT test_id,
       array_agg(DISTINCT flag_name) AS flags
FROM reports_test_results_flag_bridge tfb
JOIN reports_test rt ON rt.id = tfb.test_id
JOIN reports_repositoryflag rr ON tfb.flag_id = rr.id
WHERE rt.repoid = %(repoid)s
GROUP BY test_id
"""

ROLLUP_QUERY = f"""
WITH
  base_cte AS ({BASE_SUBQUERY}),
  failure_rate_cte AS ({TEST_AGGREGATION_SUBQUERY}),
  commits_where_fail_cte AS ({COMMITS_FAILED_SUBQUERY}),
  last_duration_cte AS ({LAST_DURATION_SUBQUERY}),
  flags_cte AS ({TEST_FLAGS_SUBQUERY})

SELECT COALESCE(rt.computed_name, rt.name) AS name,
       rt.testsuite,
       flags_cte.flags,
       results.*
FROM
  (SELECT failure_rate_cte.*,
          coalesce(commits_where_fail_cte.failed_commits_count, 0) AS commits_where_fail,
          last_duration_cte.last_duration_seconds AS last_duration
   FROM failure_rate_cte
   FULL OUTER JOIN commits_where_fail_cte USING (test_id)
   FULL OUTER JOIN last_duration_cte USING (test_id)) AS results
JOIN reports_test rt ON results.test_id = rt.id
LEFT JOIN flags_cte USING (test_id)
"""


class DailyTotals(TypedDict):
    test_id: str
    repoid: int
    pass_count: int
    fail_count: int
    skip_count: int
    flaky_fail_count: int
    branch: str
    date: date
    latest_run: datetime
    commits_where_fail: list[str]
    last_duration_seconds: float
    avg_duration_seconds: float


def get_repo_flag_ids(db_session: Session, repoid: int, flags: list[str]) -> set[int]:
    if not flags:
        return set()

    return set(
        db_session.query(RepositoryFlag.id_)
        .filter(
            RepositoryFlag.repository_id == repoid,
            RepositoryFlag.flag_name.in_(flags),
        )
        .all()
    )


def modify_structures(
    tests_to_write: dict[str, dict[str, Any]],
    test_instances_to_write: list[dict[str, Any]],
    test_flag_bridge_data: list[dict],
    daily_totals: dict[str, DailyTotals],
    testrun: test_results_parser.Testrun,
    upload_id: int,
    flag_names: list[str],
    repoid: int,
    branch: str | None,
    commit_sha: str,
    repo_flag_ids: set[int],
    flaky_test_set: set[str],
    framework: str | None,
):
    flags_hash = generate_flags_hash(flag_names)

    test_name = f"{testrun['classname']}\x1f{testrun['name']}"
    test_id = generate_test_id(
        repoid,
        testrun["testsuite"],
        test_name,
        flags_hash,
    )

    test = generate_test_dict(
        test_id, test_name, repoid, testrun, flags_hash, framework
    )
    tests_to_write[test_id] = test

    test_instance = generate_test_instance_dict(
        test_id, upload_id, testrun, commit_sha, branch, repoid
    )
    test_instances_to_write.append(test_instance)

    if repo_flag_ids:
        test_flag_bridge_data.extend(
            {"test_id": test_id, "flag_id": flag_id} for flag_id in repo_flag_ids
        )

    if test_id in daily_totals:
        update_daily_totals(
            daily_totals,
            test_id,
            testrun["duration"],
            testrun["outcome"],
        )
    else:
        create_daily_totals(
            daily_totals,
            test_id,
            repoid,
            testrun["duration"],
            testrun["outcome"],
            branch,
            commit_sha,
            flaky_test_set,
        )


def generate_test_dict(
    test_id: str,
    test_name: str,
    repoid: int,
    testrun: test_results_parser.Testrun,
    flags_hash: str,
    framework: str | None,
) -> dict[str, Any]:
    return {
        "id": test_id,
        "repoid": repoid,
        "name": test_name,
        "testsuite": testrun["testsuite"],
        "flags_hash": flags_hash,
        "framework": framework,
        "filename": testrun["filename"],
        "computed_name": testrun["computed_name"],
    }


def generate_test_instance_dict(
    test_id: str,
    upload_id: int,
    testrun: test_results_parser.Testrun,
    commit_sha: str,
    branch: str | None,
    repoid: int,
) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "upload_id": upload_id,
        "duration_seconds": testrun["duration"],
        "outcome": testrun["outcome"],
        "failure_message": testrun["failure_message"],
        "commitid": commit_sha,
        "branch": branch,
        "reduced_error_id": None,
        "repoid": repoid,
    }


def update_daily_totals(
    daily_totals: dict[str, DailyTotals],
    test_id: str,
    duration_seconds: float | None,
    outcome: Literal["pass", "failure", "error", "skip"],
):
    # logic below is a little complicated but we're basically doing:

    # (old_avg * num of values used to compute old avg) + new value
    # -------------------------------------------------------------
    #          num of values used to compute old avg + 1
    if (
        duration_seconds is not None
        and daily_totals[test_id]["avg_duration_seconds"] is not None
    ):
        daily_totals[test_id]["avg_duration_seconds"] = (
            daily_totals[test_id]["avg_duration_seconds"]
            * (
                daily_totals[test_id]["pass_count"]
                + daily_totals[test_id]["fail_count"]
            )
            + duration_seconds
        ) / (
            daily_totals[test_id]["pass_count"]
            + daily_totals[test_id]["fail_count"]
            + 1
        )

    if outcome == "pass":
        daily_totals[test_id]["pass_count"] += 1
    elif outcome == "failure" or outcome == "error":
        daily_totals[test_id]["fail_count"] += 1
    elif outcome == "skip":
        daily_totals[test_id]["skip_count"] += 1


def create_daily_totals(
    daily_totals: dict,
    test_id: str,
    repoid: int,
    duration_seconds: float | None,
    outcome: Literal["pass", "failure", "error", "skip"],
    branch: str | None,
    commit_sha: str,
    flaky_test_set: set[str],
):
    daily_totals[test_id] = {
        "test_id": test_id,
        "repoid": repoid,
        "last_duration_seconds": duration_seconds or 0.0,
        "avg_duration_seconds": duration_seconds or 0.0,
        "pass_count": 1 if outcome == "pass" else 0,
        "fail_count": 1 if outcome == "failure" or outcome == "error" else 0,
        "skip_count": 1 if outcome == "skip" else 0,
        "flaky_fail_count": 1
        if test_id in flaky_test_set and (outcome == "failure" or outcome == "error")
        else 0,
        "branch": branch,
        "date": date.today(),
        "latest_run": datetime.now(),
        "commits_where_fail": [commit_sha]
        if (outcome == "failure" or outcome == "error")
        else [],
    }


def save_tests(db_session: Session, tests_to_write: dict[str, dict[str, Any]]):
    test_data = sorted(
        tests_to_write.values(),
        key=lambda x: str(x["id"]),
    )

    test_insert = insert(Test.__table__).values(test_data)
    insert_on_conflict_do_update = test_insert.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "framework": test_insert.excluded.framework,
            "computed_name": test_insert.excluded.computed_name,
            "filename": test_insert.excluded.filename,
        },
    )
    db_session.execute(insert_on_conflict_do_update)
    db_session.commit()


def save_test_flag_bridges(db_session: Session, test_flag_bridge_data: list[dict]):
    insert_on_conflict_do_nothing_flags = (
        insert(TestFlagBridge.__table__)
        .values(test_flag_bridge_data)
        .on_conflict_do_nothing(index_elements=["test_id", "flag_id"])
    )
    db_session.execute(insert_on_conflict_do_nothing_flags)
    db_session.commit()


def save_daily_test_rollups(db_session: Session, daily_rollups: dict[str, DailyTotals]):
    sorted_rollups = sorted(daily_rollups.values(), key=lambda x: str(x["test_id"]))
    rollup_table = DailyTestRollup.__table__
    stmt = insert(rollup_table).values(sorted_rollups)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "repoid",
            "branch",
            "test_id",
            "date",
        ],
        set_={
            "last_duration_seconds": stmt.excluded.last_duration_seconds,
            "avg_duration_seconds": (
                rollup_table.c.avg_duration_seconds
                * (rollup_table.c.pass_count + rollup_table.c.fail_count)
                + stmt.excluded.avg_duration_seconds
            )
            / (rollup_table.c.pass_count + rollup_table.c.fail_count + 1),
            "latest_run": stmt.excluded.latest_run,
            "pass_count": rollup_table.c.pass_count + stmt.excluded.pass_count,
            "skip_count": rollup_table.c.skip_count + stmt.excluded.skip_count,
            "fail_count": rollup_table.c.fail_count + stmt.excluded.fail_count,
            "flaky_fail_count": rollup_table.c.flaky_fail_count
            + stmt.excluded.flaky_fail_count,
            "commits_where_fail": rollup_table.c.commits_where_fail
            + stmt.excluded.commits_where_fail,
        },
    )
    db_session.execute(stmt)
    db_session.commit()


def save_test_instances(db_session: Session, test_instance_data: list[dict]):
    insert_test_instances = insert(TestInstance.__table__).values(test_instance_data)
    db_session.execute(insert_test_instances)
    db_session.commit()


FLAKE_EXPIRY_COUNT = 30


def process_flake_for_repo_commit(
    repo_id: int,
    commit_id: str,
):
    uploads = DjangoReportSession.objects.filter(
        report__report_type=DjangoCommitReport.ReportType.TEST_RESULTS.value,
        report__commit__repository__repoid=repo_id,
        report__commit__commitid=commit_id,
        state__in=["processed", "v2_finished"],
    ).all()

    process_flakes_for_uploads(repo_id, [upload for upload in uploads])

    return {"successful": True}


def process_flakes_for_uploads(repo_id: int, uploads: list[DjangoReportSession]):
    curr_flakes = fetch_curr_flakes(repo_id)
    new_flakes: dict[str, DjangoFlake] = dict()

    rollups_to_update: list[DjangoDailyTestRollup] = []

    flaky_tests = list(curr_flakes.keys())

    for upload in uploads:
        test_instances = get_test_instances(upload, flaky_tests)
        for test_instance in test_instances:
            if test_instance.outcome == DjangoTestInstance.Outcome.PASS.value:
                flake = new_flakes.get(test_instance.test_id) or curr_flakes.get(
                    test_instance.test_id
                )
                if flake is not None:
                    update_flake(flake, test_instance)
            elif test_instance.outcome in (
                DjangoTestInstance.Outcome.FAILURE.value,
                DjangoTestInstance.Outcome.ERROR.value,
            ):
                flake = new_flakes.get(test_instance.test_id) or curr_flakes.get(
                    test_instance.test_id
                )
                if flake:
                    update_flake(flake, test_instance)
                else:
                    flake, rollup = create_flake(test_instance, repo_id)

                    new_flakes[test_instance.test_id] = flake

                    if rollup:
                        rollups_to_update.append(rollup)

        if rollups_to_update:
            DjangoDailyTestRollup.objects.bulk_update(
                rollups_to_update,
                ["flaky_fail_count"],
            )

        merge_flake_dict = {}

        if new_flakes:
            flakes_to_merge = DjangoFlake.objects.bulk_create(new_flakes.values())
            merge_flake_dict: dict[str, DjangoFlake] = {
                flake.test_id: flake for flake in flakes_to_merge
            }

        DjangoFlake.objects.bulk_update(
            curr_flakes.values(),
            [
                "count",
                "fail_count",
                "recent_passes_count",
                "end_date",
            ],
        )

        curr_flakes = {**merge_flake_dict, **curr_flakes}

        new_flakes.clear()

        upload.state = "flake_processed"
        upload.save()
        django_transaction.commit()


def get_test_instances(
    upload: DjangoReportSession,
    flaky_tests: list[str],
) -> list[DjangoTestInstance]:
    # get test instances on this upload that either:
    # - failed
    # - passed but belong to an already flaky test

    upload_filter = Q(upload_id=upload.id)
    test_failed_filter = Q(outcome=DjangoTestInstance.Outcome.ERROR.value) | Q(
        outcome=DjangoTestInstance.Outcome.FAILURE.value
    )
    test_passed_but_flaky_filter = Q(outcome=DjangoTestInstance.Outcome.PASS.value) & Q(
        test_id__in=flaky_tests
    )
    test_instances = list(
        DjangoTestInstance.objects.filter(
            upload_filter & (test_failed_filter | test_passed_but_flaky_filter)
        )
        .select_related("test")
        .all()
    )
    return test_instances


def fetch_curr_flakes(repo_id: int) -> dict[str, DjangoFlake]:
    flakes = DjangoFlake.objects.filter(
        repository_id=repo_id, end_date__isnull=True
    ).all()
    return {flake.test_id: flake for flake in flakes}


def create_flake(
    test_instance: DjangoTestInstance,
    repo_id: int,
) -> tuple[DjangoFlake, DjangoDailyTestRollup | None]:
    # retroactively mark newly caught flake as flaky failure in its rollup
    rollup = DjangoDailyTestRollup.objects.filter(
        repoid=repo_id,
        date=test_instance.created_at.date(),
        branch=test_instance.branch,
        test_id=test_instance.test_id,
    ).first()

    if rollup:
        rollup.flaky_fail_count += 1

    f = DjangoFlake(
        repository_id=repo_id,
        test=test_instance.test,
        reduced_error=None,
        count=1,
        fail_count=1,
        start_date=test_instance.created_at,
        recent_passes_count=0,
    )

    return f, rollup


def update_flake(
    flake: DjangoFlake,
    test_instance: DjangoTestInstance,
) -> None:
    flake.count += 1

    match test_instance.outcome:
        case DjangoTestInstance.Outcome.PASS.value:
            flake.recent_passes_count += 1
            if flake.recent_passes_count == FLAKE_EXPIRY_COUNT:
                flake.end_date = test_instance.created_at
        case (
            DjangoTestInstance.Outcome.FAILURE.value
            | DjangoTestInstance.Outcome.ERROR.value
        ):
            flake.fail_count += 1
            flake.recent_passes_count = 0
        case _:
            pass


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


class PGDriver(TADriver[str]):
    def __init__(
        self,
        repo_id: int,
        db_session: Session | None = None,
        flaky_test_set: set[str] | None = None,
    ):
        super().__init__(repo_id)
        self.db_session = db_session
        self.flaky_test_set = flaky_test_set

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
        if self.db_session is None:
            raise ValueError("DB session is required")

        if self.flaky_test_set is None:
            self.flaky_test_set = set(self.get_repo_flakes().keys())

        tests_to_write: dict[str, dict[str, Any]] = {}
        test_instances_to_write: list[dict[str, Any]] = []
        daily_totals: dict[str, DailyTotals] = dict()
        test_flag_bridge_data: list[dict] = []

        repo_flag_ids = get_repo_flag_ids(self.db_session, self.repo_id, flag_names)

        for testrun in testruns:
            modify_structures(
                tests_to_write,
                test_instances_to_write,
                test_flag_bridge_data,
                daily_totals,
                testrun,
                upload_id,
                flag_names,
                self.repo_id,
                branch_name,
                commit_sha,
                repo_flag_ids,
                self.flaky_test_set,
                framework,
            )

        if len(tests_to_write) > 0:
            save_tests(self.db_session, tests_to_write)

        if len(test_flag_bridge_data) > 0:
            save_test_flag_bridges(self.db_session, test_flag_bridge_data)

        if len(daily_totals) > 0:
            save_daily_test_rollups(self.db_session, daily_totals)

        if len(test_instances_to_write) > 0:
            save_test_instances(self.db_session, test_instances_to_write)

    def cache_analytics(self, buckets: list[str], branch: str | None) -> None:
        storage_service = shared.storage.get_appropriate_storage_service(self.repo_id)

        if get_config("setup", "database", "read_replica_enabled", default=False):
            connection = connections["default_read"]
        else:
            connection = connections["default"]

        with connection.cursor() as cursor:
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
                query_params = {
                    "repoid": self.repo_id,
                    "branch": branch,
                    "interval_start": f"{interval_start} days",
                    # SQL `BETWEEN` syntax is equivalent to `<= end`, with an inclusive end date,
                    # thats why we do a `+1` here:
                    "interval_end": f"{interval_end + 1 if interval_end else 0} days",
                }

                cursor.execute(ROLLUP_QUERY, query_params)
                aggregation_of_test_results = cursor.fetchall()

                df = pl.DataFrame(
                    aggregation_of_test_results,
                    [
                        "name",
                        "testsuite",
                        ("flags", pl.List(pl.String)),
                        "test_id",
                        "failure_rate",
                        "flake_rate",
                        ("updated_at", pl.Datetime(time_zone=dt.UTC)),
                        "avg_duration",
                        "total_fail_count",
                        "total_flaky_fail_count",
                        "total_pass_count",
                        "total_skip_count",
                        "commits_where_fail",
                        "last_duration",
                    ],
                    orient="row",
                )

                serialized_table = df.write_ipc(None)
                serialized_table.seek(0)  # avoids Stream must be at beginning errors

                storage_key = (
                    f"test_results/rollups/{self.repo_id}/{branch}/{interval_start}"
                    if interval_end is None
                    else f"test_results/rollups/{self.repo_id}/{branch}/{interval_start}_{interval_end}"
                )

                for bucket in buckets:
                    storage_service.write_file(bucket, storage_key, serialized_table)

    def pr_comment_agg(self, commit_sha: str) -> PRCommentAggResult:
        if self.db_session is None:
            raise ValueError("DB session is required")

        test_summary = get_test_summary_for_commit(
            self.db_session, self.repo_id, commit_sha
        )

        return {
            "commit_sha": commit_sha,
            "passed_ct": test_summary.get("pass", 0),
            "failed_ct": test_summary.get("failure", 0) + test_summary.get("error", 0),
            "skipped_ct": test_summary.get("skip", 0),
            "flaky_failed_ct": 0,
        }

    def pr_comment_fail(self, commit_sha: str) -> list[PRCommentFailResult[str]]:
        if self.db_session is None:
            raise ValueError("DB session is required")

        test_instances = latest_failures_for_commit(
            self.db_session, self.repo_id, commit_sha
        )

        return [
            {
                "computed_name": instance.test.computed_name
                or f"{instance.test.testsuite}.{instance.test.name.replace('\x1f', '.')}",
                "failure_message": instance.failure_message,
                "id": instance.test.id,
                "duration_seconds": instance.duration_seconds,
                "upload_id": instance.upload_id,
            }
            for instance in test_instances
        ]

    def write_flakes(self, uploads: list[DjangoReportSession]) -> None:
        return process_flakes_for_uploads(self.repo_id, uploads)

    def get_repo_flakes(
        self, test_ids: tuple[str, ...] | None = None
    ) -> dict[str, FlakeInfo]:
        if self.db_session is None:
            raise ValueError("DB session is required")
        if test_ids:
            matching_flakes = list(
                self.db_session.query(Flake)
                .filter(
                    Flake.repoid == self.repo_id,
                    Flake.testid.in_(test_ids),
                    Flake.end_date.is_(None),
                    Flake.count != (Flake.recent_passes_count + Flake.fail_count),
                )
                .all()
            )
        else:
            matching_flakes = list(
                self.db_session.query(Flake)
                .filter(
                    Flake.repoid == self.repo_id,
                    Flake.end_date.is_(None),
                    Flake.count != (Flake.recent_passes_count + Flake.fail_count),
                )
                .all()
            )

        flaky_test_ids = {
            flake.testid: FlakeInfo(flake.fail_count, flake.count)
            for flake in matching_flakes
        }
        return flaky_test_ids
