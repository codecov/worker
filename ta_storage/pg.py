from datetime import date, datetime
from typing import Any, Literal, TypedDict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from test_results_parser import Testrun

from database.models import (
    DailyTestRollup,
    RepositoryFlag,
    Test,
    TestFlagBridge,
    TestInstance,
    Upload,
)
from services.test_results import generate_flags_hash, generate_test_id
from ta_storage.base import TADriver


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
    testrun: Testrun,
    upload: Upload,
    repoid: int,
    branch: str | None,
    commit_sha: str,
    repo_flag_ids: set[int],
    flaky_test_set: set[str],
    framework: str | None,
):
    flags_hash = generate_flags_hash(upload.flag_names)
    test_id = generate_test_id(
        repoid,
        testrun["testsuite"],
        testrun["name"],
        flags_hash,
    )

    test = generate_test_dict(test_id, repoid, testrun, flags_hash, framework)
    tests_to_write[test_id] = test

    test_instance = generate_test_instance_dict(
        test_id, upload, testrun, commit_sha, branch, repoid
    )
    test_instances_to_write.append(test_instance)

    if repo_flag_ids:
        test_flag_bridge_data.extend(
            {"test_id": test_id, "flag_id": flag_id} for flag_id in repo_flag_ids
        )

    if test["id"] in daily_totals:
        update_daily_totals(
            daily_totals,
            test["id"],
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
    repoid: int,
    testrun: Testrun,
    flags_hash: str,
    framework: str | None,
) -> dict[str, Any]:
    return {
        "id": test_id,
        "repoid": repoid,
        "name": f"{testrun['classname']}\x1f{testrun['name']}",
        "testsuite": testrun["testsuite"],
        "flags_hash": flags_hash,
        "framework": framework,
        "filename": testrun["filename"],
        "computed_name": testrun["computed_name"],
    }


def generate_test_instance_dict(
    test_id: str,
    upload: Upload,
    testrun: Testrun,
    commit_sha: str,
    branch: str | None,
    repoid: int,
) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "upload_id": upload.id,
        "duration_seconds": testrun["duration"],
        "outcome": testrun["outcome"],
        "failure_message": testrun["failure_message"],
        "commitid": commit_sha,
        "branch": branch,
        "reduced_error_id": None,
        "repoid": repoid,
    }


def update_daily_totals(
    daily_totals: dict,
    test_id: str,
    duration_seconds: float | None,
    outcome: Literal["pass", "failure", "error", "skip"],
):
    daily_totals[test_id]["last_duration_seconds"] = duration_seconds

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
        "last_duration_seconds": duration_seconds,
        "avg_duration_seconds": duration_seconds,
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
        index_elements=["repoid", "name", "testsuite", "flags_hash"],
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


class PGDriver(TADriver):
    def __init__(self, db_session: Session, flaky_test_set: set):
        self.db_session = db_session
        self.flaky_test_set = flaky_test_set

    def write_testruns(
        self,
        timestamp: int | None,
        repo_id: int,
        commit_sha: str,
        branch_name: str,
        upload: Upload,
        framework: str | None,
        testruns: list[Testrun],
    ):
        tests_to_write: dict[str, dict[str, Any]] = {}
        test_instances_to_write: list[dict[str, Any]] = []
        daily_totals: dict[str, DailyTotals] = dict()
        test_flag_bridge_data: list[dict] = []

        repo_flag_ids = get_repo_flag_ids(self.db_session, repo_id, upload.flag_names)

        for testrun in testruns:
            modify_structures(
                tests_to_write,
                test_instances_to_write,
                test_flag_bridge_data,
                daily_totals,
                testrun,
                upload,
                repo_id,
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

        upload.state = "v2_persisted"
        self.db_session.commit()
