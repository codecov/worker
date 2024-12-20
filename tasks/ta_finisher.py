import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, TypedDict

from asgiref.sync import async_to_sync
from msgpack import unpackb
from shared.reports.types import UploadType
from shared.typings.torngit import AdditionalData
from shared.yaml import UserYaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import celery_app
from database.enums import FlakeSymptomType, ReportType, TestResultsProcessingError
from database.models import (
    Commit,
    CommitReport,
    DailyTestRollup,
    Flake,
    RepositoryFlag,
    Test,
    TestFlagBridge,
    TestInstance,
    TestResultReportTotals,
    Upload,
)
from helpers.checkpoint_logger.flows import TestResultsFlow
from helpers.notifier import NotifierResult
from helpers.string import EscapeEnum, Replacement, StringEscaper, shorten_file_paths
from services.activation import activate_user
from services.lock_manager import LockManager, LockRetry, LockType
from services.redis import get_redis_connection
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.seats import ShouldActivateSeat, determine_seat_activation
from services.test_results import (
    FlakeInfo,
    TestResultsNotificationFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    generate_flags_hash,
    generate_test_id,
    get_test_summary_for_commit,
    latest_failures_for_commit,
    should_do_flaky_detection,
)
from tasks.base import BaseCodecovTask
from tasks.cache_test_rollups import cache_test_rollups_task_name
from tasks.notify import notify_task_name
from tasks.process_flakes import process_flakes_task_name

log = logging.getLogger(__name__)

ta_finisher_task_name = "app.tasks.test_results.TAFinisher"

ESCAPE_FAILURE_MESSAGE_DEFN = [
    Replacement(["\r"], "", EscapeEnum.REPLACE),
]


@dataclass
class FlakeUpdateInfo:
    new_flake_ids: list[str]
    old_flake_ids: list[str]
    newly_calculated_flakes: dict[str, set[FlakeSymptomType]]


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


def create_daily_totals(
    daily_totals: dict,
    test_id: str,
    repoid: int,
    duration_seconds: float,
    outcome: Literal["pass", "failure", "error", "skip"],
    branch: str,
    commitid: str,
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
        "commits_where_fail": [commitid]
        if (outcome == "failure" or outcome == "error")
        else [],
    }


def update_daily_totals(
    daily_totals: dict,
    test_id: str,
    duration_seconds: float,
    outcome: Literal["pass", "failure", "error", "skip"],
):
    daily_totals[test_id]["last_duration_seconds"] = duration_seconds

    # logic below is a little complicated but we're basically doing:

    # (old_avg * num of values used to compute old avg) + new value
    # -------------------------------------------------------------
    #          num of values used to compute old avg + 1
    daily_totals[test_id]["avg_duration_seconds"] = (
        daily_totals[test_id]["avg_duration_seconds"]
        * (daily_totals[test_id]["pass_count"] + daily_totals[test_id]["fail_count"])
        + duration_seconds
    ) / (daily_totals[test_id]["pass_count"] + daily_totals[test_id]["fail_count"] + 1)

    if outcome == "pass":
        daily_totals[test_id]["pass_count"] += 1
    elif outcome == "failure" or outcome == "error":
        daily_totals[test_id]["fail_count"] += 1
    elif outcome == "skip":
        daily_totals[test_id]["skip_count"] += 1


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


class TAFinisherTask(BaseCodecovTask, name=ta_finisher_task_name):
    def run_impl(
        self,
        db_session: Session,
        chord_result: list[bool],
        *,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        **kwargs,
    ):
        repoid = int(repoid)

        self.extra_dict: dict[str, Any] = {"commit_yaml": commit_yaml}
        log.info("Starting test results finisher task", extra=self.extra_dict)

        lock_manager = LockManager(
            repoid=repoid,
            commitid=commitid,
            report_type=ReportType.COVERAGE,
            lock_timeout=max(80, self.hard_time_limit_task),
        )

        try:
            # this needs to be the coverage notification lock
            # since both tests post/edit the same comment
            with lock_manager.locked(
                LockType.NOTIFICATION,
                retry_num=self.request.retries,
            ):
                finisher_result = self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=UserYaml.from_dict(commit_yaml),
                    previous_result=chord_result,
                    **kwargs,
                )
            if finisher_result["queue_notify"]:
                self.app.tasks[notify_task_name].apply_async(
                    args=None,
                    kwargs=dict(
                        repoid=repoid,
                        commitid=commitid,
                        current_yaml=commit_yaml,
                    ),
                )

            return finisher_result

        except LockRetry as retry:
            self.retry(max_retries=5, countdown=retry.countdown)

    def process_impl_within_lock(
        self,
        *,
        db_session: Session,
        repoid: int,
        commitid: str,
        commit_yaml: UserYaml,
        previous_result: list[bool],
        **kwargs,
    ):
        log.info("Running test results finishers", extra=self.extra_dict)
        TestResultsFlow.log(TestResultsFlow.TEST_RESULTS_FINISHER_BEGIN)

        commit: Commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        assert commit, "commit not found"
        repo = commit.repository

        uploads = (
            db_session.query(Upload)
            .join(CommitReport)
            .filter(
                CommitReport.commit_id == commit.id,
                CommitReport.report_type == ReportType.TEST_RESULTS.value,
            )
            .all()
        )

        redis_client = get_redis_connection()

        tests_to_write: dict[str, dict[str, Any]] = {}
        test_instances_to_write: list[dict[str, Any]] = []
        daily_totals: dict[str, DailyTotals] = dict()
        test_flag_bridge_data: list[dict] = []

        repo_flakes: list[Flake] = (
            db_session.query(Flake.testid)
            .filter(Flake.repoid == repoid, Flake.end_date.is_(None))
            .all()
        )

        flaky_test_set = {flake.testid for flake in repo_flakes}

        for upload in uploads:
            tests_to_write: dict[str, dict[str, Any]] = {}
            test_instances_to_write: list[dict[str, Any]] = []
            daily_totals: dict[str, DailyTotals] = dict()
            test_flag_bridge_data: list[dict] = []

            repo_flag_ids = get_repo_flag_ids(db_session, repoid, upload.flag_names)
            intermediate_key = f"ta/intermediate/{repo.repoid}/{commitid}/{upload.id}"
            msgpacked = redis_client.get(intermediate_key)
            m = unpackb(msgpacked)

            for msg in m:
                framework = msg["framework"]
                for testrun in msg["testruns"]:
                    flags_hash = generate_flags_hash(upload.flag_names)
                    test_id = generate_test_id(
                        repoid,
                        testrun["testsuite"],
                        testrun["name"],
                        flags_hash,
                    )
                    test = {
                        "id": test_id,
                        "repoid": repoid,
                        "name": f"{testrun['classname']}\x1f{testrun['name']}",
                        "testsuite": testrun["testsuite"],
                        "flags_hash": flags_hash,
                        "framework": framework,
                        "filename": testrun["filename"],
                        "computed_name": testrun["computed_name"],
                    }
                    tests_to_write[test_id] = test

                    test_instance = {
                        "test_id": test_id,
                        "upload_id": upload.id,
                        "duration_seconds": testrun["duration"],
                        "outcome": testrun["outcome"],
                        "failure_message": testrun["failure_message"],
                        "commitid": commitid,
                        "branch": commit.branch,
                        "reduced_error_id": None,
                        "repoid": repoid,
                    }
                    test_instances_to_write.append(test_instance)

                    if repo_flag_ids:
                        test_flag_bridge_data.extend(
                            {"test_id": test_id, "flag_id": flag_id}
                            for flag_id in repo_flag_ids
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
                            commit.branch,
                            commitid,
                            flaky_test_set,
                        )

            # Upsert Tests
            if len(tests_to_write) > 0:
                sorted_tests = sorted(
                    tests_to_write.values(),
                    key=lambda x: str(x["id"]),
                )
                self.save_tests(db_session, sorted_tests)

                db_session.commit()
                log.info("Upserted tests to database", extra=dict(upload_id=upload.id))

            if len(test_flag_bridge_data) > 0:
                self.save_test_flag_bridges(db_session, test_flag_bridge_data)

                db_session.commit()
                log.info(
                    "Inserted new test flag bridges to database",
                    extra=dict(upload_id=upload.id),
                )

            if len(daily_totals) > 0:
                sorted_rollups = sorted(
                    daily_totals.values(), key=lambda x: str(x["test_id"])
                )
                self.save_daily_test_rollups(db_session, sorted_rollups)

                db_session.commit()
                log.info(
                    "Upserted daily test rollups to database",
                    extra=dict(upload_id=upload.id),
                )

            # Save TestInstances
            if len(test_instances_to_write) > 0:
                self.save_test_instances(db_session, test_instances_to_write)

                db_session.commit()
                log.info(
                    "Inserted test instances to database",
                    extra=dict(upload_id=upload.id),
                )

            upload.state = "finished"
            db_session.commit()

            redis_client.delete(intermediate_key)

        if should_do_flaky_detection(repo, commit_yaml):
            if commit.merged is True or commit.branch == repo.branch:
                self.app.tasks[process_flakes_task_name].apply_async(
                    kwargs=dict(
                        repo_id=repoid,
                        commit_id=commit.commitid,
                    )
                )

        if commit.branch is not None:
            self.app.tasks[cache_test_rollups_task_name].apply_async(
                kwargs=dict(repoid=repoid, branch=commit.branch),
            )

        commit_report = commit.commit_report(ReportType.TEST_RESULTS)

        totals = commit_report.test_result_totals
        if totals is None:
            totals = TestResultReportTotals(
                report_id=commit_report.id,
            )
            totals.passed = 0
            totals.skipped = 0
            totals.failed = 0
            totals.error = str(TestResultsProcessingError.NO_SUCCESS)
            db_session.add(totals)
            db_session.flush()

        if not any(previous_result):
            # every processor errored, nothing to notify on
            queue_notify = False

            # if error is None this whole process should be a noop
            if totals.error is not None:
                # make an attempt to make test results comment
                notifier = TestResultsNotifier(commit, commit_yaml)
                success, reason = notifier.error_comment()

                # also make attempt to make coverage comment
                queue_notify = True

            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                "queue_notify": queue_notify,
            }

        # if we succeed once, error should be None for this commit forever
        if totals.error is not None:
            totals.error = None
            db_session.flush()

        cached_uploads: dict[int, dict] = dict()
        escaper = StringEscaper(ESCAPE_FAILURE_MESSAGE_DEFN)
        shorten_paths = commit_yaml.read_yaml_field(
            "test_analytics", "shorten_paths", _else=True
        )

        test_summary = get_test_summary_for_commit(db_session, repoid, commitid)
        failed_tests = test_summary.get("error", 0) + test_summary.get("failure", 0)
        passed_tests = test_summary.get("pass", 0)
        skipped_tests = test_summary.get("skip", 0)

        failures = []
        if failed_tests:
            failed_test_instances = latest_failures_for_commit(
                db_session, repoid, commitid
            )

            for test_instance in failed_test_instances:
                failure_message = test_instance.failure_message
                if failure_message is not None:
                    if shorten_paths:
                        failure_message = shorten_file_paths(failure_message)
                    failure_message = escaper.replace(failure_message)

                if test_instance.upload_id not in cached_uploads:
                    upload = test_instance.upload
                    cached_uploads[test_instance.upload_id] = {
                        "flag_names": sorted(upload.flag_names),
                        "build_url": upload.build_url,
                    }
                upload = cached_uploads[test_instance.upload_id]

                failures.append(
                    TestResultsNotificationFailure(
                        display_name=test_instance.test.computed_name
                        if test_instance.test.computed_name is not None
                        else test_instance.test.name,
                        failure_message=failure_message,
                        test_id=test_instance.test_id,
                        envs=upload["flag_names"],
                        duration_seconds=test_instance.duration_seconds,
                        build_url=upload["build_url"],
                    )
                )

        totals.passed = passed_tests
        totals.skipped = skipped_tests
        totals.failed = failed_tests
        db_session.flush()

        if failed_tests == 0:
            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                "queue_notify": True,
            }

        additional_data: AdditionalData = {"upload_type": UploadType.TEST_RESULTS}
        repo_service = get_repo_provider_service(repo, additional_data=additional_data)
        pull = async_to_sync(fetch_and_update_pull_request_information_from_commit)(
            repo_service, commit, commit_yaml
        )

        if pull is not None:
            activate_seat_info = determine_seat_activation(pull)

            should_show_upgrade_message = True

            match activate_seat_info.should_activate_seat:
                case ShouldActivateSeat.AUTO_ACTIVATE:
                    assert activate_seat_info.owner_id
                    assert activate_seat_info.author_id
                    successful_activation = activate_user(
                        db_session=db_session,
                        org_ownerid=activate_seat_info.owner_id,
                        user_ownerid=activate_seat_info.author_id,
                    )
                    if successful_activation:
                        self.schedule_new_user_activated_task(
                            activate_seat_info.owner_id,
                            activate_seat_info.author_id,
                        )
                        should_show_upgrade_message = False
                case ShouldActivateSeat.MANUAL_ACTIVATE:
                    pass
                case ShouldActivateSeat.NO_ACTIVATE:
                    should_show_upgrade_message = False

            if should_show_upgrade_message:
                notifier = TestResultsNotifier(
                    commit, commit_yaml, _pull=pull, _repo_service=repo_service
                )
                success, reason = notifier.upgrade_comment()

                self.extra_dict["success"] = success
                self.extra_dict["reason"] = reason
                log.info("Made upgrade comment", extra=self.extra_dict)

                return {
                    "notify_attempted": True,
                    "notify_succeeded": success,
                    "queue_notify": False,
                }

        flaky_tests = dict()
        if should_do_flaky_detection(repo, commit_yaml):
            flaky_tests = self.get_flaky_tests(db_session, repoid, failures)

        failures = sorted(failures, key=lambda x: x.duration_seconds)[:3]
        payload = TestResultsNotificationPayload(
            failed_tests, passed_tests, skipped_tests, failures, flaky_tests
        )
        notifier = TestResultsNotifier(
            commit, commit_yaml, payload=payload, _pull=pull, _repo_service=repo_service
        )
        notifier_result = notifier.notify()
        success = True if notifier_result is NotifierResult.COMMENT_POSTED else False
        TestResultsFlow.log(TestResultsFlow.TEST_RESULTS_NOTIFY)

        if len(flaky_tests):
            log.info(
                "Detected failure on test that has been identified as flaky",
                extra=dict(
                    success=success,
                    notifier_result=notifier_result.value,
                    test_ids=list(flaky_tests.keys()),
                ),
            )

        self.extra_dict["success"] = success
        self.extra_dict["notifier_result"] = notifier_result.value
        log.info("Finished test results notify", extra=self.extra_dict)

        return {
            "notify_attempted": True,
            "notify_succeeded": success,
            "queue_notify": False,
        }

    def get_flaky_tests(
        self,
        db_session: Session,
        repoid: int,
        failures: list[TestResultsNotificationFailure],
    ) -> dict[str, FlakeInfo]:
        failure_test_ids = [failure.test_id for failure in failures]

        matching_flakes = list(
            db_session.query(Flake)
            .filter(
                Flake.repoid == repoid,
                Flake.testid.in_(failure_test_ids),
                Flake.end_date.is_(None),
                Flake.count != (Flake.recent_passes_count + Flake.fail_count),
            )
            .limit(100)
            .all()
        )

        flaky_test_ids = {
            flake.testid: FlakeInfo(flake.fail_count, flake.count)
            for flake in matching_flakes
        }
        return flaky_test_ids

    def save_tests(self, db_session: Session, test_data: list[dict]):
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

    def save_daily_test_rollups(self, db_session: Session, daily_rollups: list[dict]):
        rollup_table = DailyTestRollup.__table__
        stmt = insert(rollup_table).values(daily_rollups)
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

    def save_test_instances(self, db_session: Session, test_instance_data: list[dict]):
        insert_test_instances = insert(TestInstance.__table__).values(
            test_instance_data
        )
        db_session.execute(insert_test_instances)
        db_session.commit()

    def save_test_flag_bridges(
        self, db_session: Session, test_flag_bridge_data: list[dict]
    ):
        insert_on_conflict_do_nothing_flags = (
            insert(TestFlagBridge.__table__)
            .values(test_flag_bridge_data)
            .on_conflict_do_nothing(index_elements=["test_id", "flag_id"])
        )
        db_session.execute(insert_on_conflict_do_nothing_flags)
        db_session.commit()


RegisteredTAFinisherTask = celery_app.register_task(TAFinisherTask())
ta_finisher_task = celery_app.tasks[RegisteredTAFinisherTask.name]
