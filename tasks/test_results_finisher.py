import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict

from asgiref.sync import async_to_sync
from sentry_sdk import metrics
from shared.yaml import UserYaml
from test_results_parser import Outcome

from app import celery_app
from database.enums import FlakeSymptomType, ReportType
from database.models import Commit, Flake, Test, TestResultReportTotals
from helpers.string import EscapeEnum, Replacement, StringEscaper, shorten_file_paths
from rollouts import FLAKY_TEST_DETECTION
from services.failure_normalizer import FailureNormalizer
from services.flake_detection import (
    DefaultBranchFailureDetector,
    DiffOutcomeDetector,
    FlakeDetectionEngine,
    UnrelatedMatchesDetector,
)
from services.lock_manager import LockManager, LockRetry, LockType
from services.test_results import (
    TestResultsNotificationFailure,
    TestResultsNotificationFlake,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    latest_test_instances_for_a_given_commit,
)
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask
from tasks.notify import notify_task_name

log = logging.getLogger(__name__)

test_results_finisher_task_name = "app.tasks.test_results.TestResultsFinisherTask"

ESCAPE_FAILURE_MESSAGE_DEFN = [
    Replacement(['"'], "&quot;", EscapeEnum.REPLACE),
    Replacement(["'"], "&apos;", EscapeEnum.REPLACE),
    Replacement(["<"], "&lt;", EscapeEnum.REPLACE),
    Replacement([">"], "&gt;", EscapeEnum.REPLACE),
    Replacement(["?"], "&amp;", EscapeEnum.REPLACE),
    Replacement(["\r"], "", EscapeEnum.REPLACE),
    Replacement(["\n"], "<br>", EscapeEnum.REPLACE),
]


@dataclass
class FlakeUpdateInfo:
    new_flake_ids: list[str]
    old_flake_ids: list[str]
    newly_calculated_flakes: dict[str, set[FlakeSymptomType]]


class TestResultsFinisherTask(BaseCodecovTask, name=test_results_finisher_task_name):
    def run_impl(
        self,
        db_session,
        chord_result: Dict[str, Any],
        *,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        **kwargs,
    ):
        repoid = int(repoid)
        commit_yaml = UserYaml.from_dict(commit_yaml)

        log.info(
            "Starting test results finisher task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
            ),
        )

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
                return self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    previous_result=chord_result,
                    **kwargs,
                )
        except LockRetry as retry:
            self.retry(max_retries=5, countdown=retry.countdown)

    def process_impl_within_lock(
        self,
        *,
        db_session,
        repoid: int,
        commitid: str,
        commit_yaml: UserYaml,
        previous_result: Dict[str, Any],
        **kwargs,
    ):
        log.info(
            "Running test results finishers",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                parent_task=self.request.parent_id,
            ),
        )

        commit: Commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        assert commit, "commit not found"

        if self.check_if_no_success(previous_result):
            # every processor errored, nothing to notify on
            metrics.incr(
                "test_results.finisher",
                tags={"status": "failure", "reason": "no_successful_processing"},
            )
            return {"notify_attempted": False, "notify_succeeded": False}

        commit_report = commit.commit_report(ReportType.TEST_RESULTS)
        with metrics.timing("test_results.finisher.fetch_latest_test_instances"):
            test_instances = latest_test_instances_for_a_given_commit(
                db_session, commit.id_
            )

        failed_tests = 0
        passed_tests = 0
        skipped_tests = 0

        escaper = StringEscaper(ESCAPE_FAILURE_MESSAGE_DEFN)

        failures = []

        for test_instance in test_instances:
            if test_instance.outcome == str(
                Outcome.Failure
            ) or test_instance.outcome == str(Outcome.Error):
                failed_tests += 1

                flag_names = sorted(test_instance.upload.flag_names)

                failure_message = test_instance.failure_message

                if commit_yaml.read_yaml_field(
                    "test_analytics", "shorten_paths", _else=True
                ):
                    failure_message = shorten_file_paths(failure_message)

                failure_message = escaper.replace(failure_message)

                failures.append(
                    TestResultsNotificationFailure(
                        testsuite=test_instance.test.testsuite,
                        testname=test_instance.test.name,
                        failure_message=failure_message,
                        test_id=test_instance.test_id,
                        envs=flag_names,
                    )
                )
            elif test_instance.outcome == str(Outcome.Skip):
                skipped_tests += 1
            elif test_instance.outcome == str(Outcome.Pass):
                passed_tests += 1

        totals = commit_report.test_result_totals
        if totals is None:
            totals = TestResultReportTotals(
                report_id=commit_report.id,
            )
            db_session.add(totals)
        totals.passed = passed_tests
        totals.skipped = skipped_tests
        totals.failed = failed_tests
        db_session.flush()

        if failed_tests == 0:
            metrics.incr(
                "test_results.finisher",
                tags={"status": "normal_notify_called", "reason": "all_tests_passed"},
            )
            self.app.tasks[notify_task_name].apply_async(
                args=None,
                kwargs=dict(
                    repoid=repoid, commitid=commitid, current_yaml=commit_yaml.to_dict()
                ),
            )
            return {"notify_attempted": False, "notify_succeeded": False}

        metrics.incr(
            "test_results.finisher",
            tags={"status": "success", "reason": "tests_failed"},
        )
        flaky_tests = None

        if FLAKY_TEST_DETECTION.check_value(repo_id=repoid):
            flaky_tests, tests = self.get_flaky_tests(db_session, repoid)

        notifier = TestResultsNotifier(commit, commit_yaml)

        failures = sorted(failures, key=lambda x: x.testsuite + x.testname)
        payload = TestResultsNotificationPayload(
            failed_tests, passed_tests, skipped_tests, failures, flaky_tests
        )

        with metrics.timing("test_results.finisher.notification"):
            success, reason = async_to_sync(notifier.notify)(payload)

        log.info(
            "Finished test results notify",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                parent_task=self.request.parent_id,
                success=success,
            ),
        )

        # using a var as a tag here will be fine as it's a boolean
        metrics.incr(
            "test_results.finisher.test_result_notifier",
            tags={"status": success, "reason": reason},
        )
        if FLAKY_TEST_DETECTION.check_value(repo_id=repoid):
            with metrics.timing("test_results.finisher.run_flaky_test_detection"):
                success, reason = self.run_flaky_test_detection(
                    db_session, repoid, tests, notifier, payload
                )

            metrics.incr(
                "test_results.finisher.flaky_test_detection",
                tags={"status": success, "reason": reason},
            )

        return {"notify_attempted": True, "notify_succeeded": success}

    def get_flaky_tests(self, db_session, repoid):
        flaky_tests = dict()
        # get current flaky test
        tests = db_session.query(Test).filter(Test.repoid == repoid).all()
        for test in tests:
            if test.flakes is not None:
                for flake in test.flakes:
                    if flake.active == True:
                        symptom_set = set()
                        for instance in test.flake.testinstances:
                            symptom_set |= set(instance.flaky_symptoms)

                        flaky_tests[test.test_id] = TestResultsNotificationFlake(
                            list(symptom_set),
                            False,
                        )

        return flaky_tests, tests

    def run_flaky_test_detection(
        self,
        db_session,
        repoid,
        tests: list[Test],
        notifier: TestResultsNotifier,
        payload: TestResultsNotificationPayload,
    ):
        ignore_predefined = read_yaml_field(
            "test_analytics", "ignore_predefined", _else=False
        )

        user_normalization_regex = read_yaml_field(
            "test_analytics", "normalization_regex", _else=dict()
        )

        failure_normalizer = FailureNormalizer(
            user_normalization_regex, ignore_predefined
        )

        default_branch_failure_detector = DefaultBranchFailureDetector(
            db_session, repoid, "main"
        )
        unrelated_matches_detector = UnrelatedMatchesDetector()
        diff_outcome_detector = DiffOutcomeDetector()

        flake_detection_engine = FlakeDetectionEngine(
            db_session,
            repoid,
            [
                default_branch_failure_detector,
                unrelated_matches_detector,
                diff_outcome_detector,
            ],
            failure_normalizer,
        )

        current_state_of_repo_flakes = flake_detection_engine.detect_flakes()

        new_flake_ids, old_flake_ids = self.get_flake_diff(
            current_state_of_repo_flakes, payload.flaky_tests
        )

        flakes_to_notify = defaultdict(set)

        for test_id, instance_dict in current_state_of_repo_flakes.items():
            if test_id in new_flake_ids:
                flake = Flake(test_id=test_id, active=True)
                db_session.add(flake)
                db_session.flush()

                for instance, symptoms in instance_dict.items():
                    instance.flake = flake

                    flakes_to_notify[test_id] |= set(symptoms)
            elif test_id in old_flake_ids:
                flake = db_session.query(Flake).filter(
                    Flake.test_id == test_id, Flake.active == True
                )
                flake.active = False
            else:
                flake = db_session.query(Flake).filter(
                    Flake.test_id == test_id, Flake.active == True
                )
                for instance, symptoms in instance_dict.items():
                    instance.flake = flake
                    instance.flake_symptom = symptoms

                    flakes_to_notify[test_id] |= set(symptoms)

            db_session.flush()

        for test_id, flake_symptoms in flakes_to_notify.items():
            payload.flaky_tests[test_id] = TestResultsNotificationFlake(
                list(flake_symptoms),
                True,
            )

        success, reason = async_to_sync(notifier.notify)(payload)

        return success, reason

    def get_flake_diff(
        self,
        newly_calculated_flakes: dict[str, FlakeSymptomType],
        existing_flakes_from_db: dict[str, TestResultsNotificationFlake],
    ):
        newly_discovered_flakes = set(newly_calculated_flakes.keys()) - set(
            existing_flakes_from_db.keys()
        )
        no_longer_flakes = set(existing_flakes_from_db.keys()) - set(
            newly_calculated_flakes.keys()
        )

        return list(newly_discovered_flakes), list(no_longer_flakes)

    def check_if_no_success(self, previous_result):
        return all(
            (
                testrun_list["successful"] is False
                for result in previous_result
                for testrun_list in result
            )
        )

    def check_if_no_failures(self, testrun_list):
        return all(
            [instance.outcome != str(Outcome.Failure) for instance in testrun_list]
        )


RegisteredTestResultsFinisherTask = celery_app.register_task(TestResultsFinisherTask())
test_results_finisher_task = celery_app.tasks[RegisteredTestResultsFinisherTask.name]
