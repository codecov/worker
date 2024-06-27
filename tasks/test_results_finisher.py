import logging
from dataclasses import dataclass
from typing import Any, Dict

from asgiref.sync import async_to_sync
from sentry_sdk import metrics
from shared.yaml import UserYaml
from test_results_parser import Outcome

from app import celery_app
from database.enums import FlakeSymptomType, ReportType, TestResultsProcessingError
from database.models import Commit, TestResultReportTotals
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from helpers.checkpoint_logger.flows import TestResultsFlow
from helpers.string import EscapeEnum, Replacement, StringEscaper, shorten_file_paths
from rollouts import FLAKY_TEST_DETECTION
from services.failure_normalizer import FailureNormalizer
from services.flake_detection import (
    DefaultBranchFailureDetector,
    DiffOutcomeDetector,
    FlakeDetectionEngine,
    FlakeDetectionResult,
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
QUEUE_NOTIFY_KEY = "queue_notify"


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
                finisher_result = self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    previous_result=chord_result,
                    **kwargs,
                )
            if finisher_result[QUEUE_NOTIFY_KEY]:
                self.app.tasks[notify_task_name].apply_async(
                    args=None,
                    kwargs=dict(
                        repoid=repoid,
                        commitid=commitid,
                        current_yaml=commit_yaml.to_dict(),
                    ),
                )

            return finisher_result

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

        checkpoints = checkpoints_from_kwargs(TestResultsFlow, kwargs)

        checkpoints.log(TestResultsFlow.TEST_RESULTS_FINISHER_BEGIN)
        
        # TODO: remove this later, we can do this now because there aren't many users using this
        metrics.distribution(
            "test_results_processing_time",
            checkpoints._subflow_duration(
                TestResultsFlow.TEST_RESULTS_BEGIN,
                TestResultsFlow.TEST_RESULTS_FINISHER_BEGIN,
            ),
            unit="millisecond",
            tags={"repoid": repoid},
        )

        commit: Commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        assert commit, "commit not found"

        notifier = TestResultsNotifier(commit, commit_yaml)

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

        with metrics.timing("test_results.finisher.fetch_latest_test_instances"):
            test_instances = latest_test_instances_for_a_given_commit(
                db_session, commit.id_
            )

        if self.check_if_no_success(previous_result):
            # every processor errored, nothing to notify on
            metrics.incr(
                "test_results.finisher",
                tags={"status": "failure", "reason": "no_successful_processing"},
            )

            queue_notify = False

            # if error is None this whole process should be a noop
            if totals.error is not None:
                # make an attempt to make test results comment
                success, reason = async_to_sync(notifier.error_comment)()

                # also make attempt to make coverage comment
                queue_notify = True

                metrics.incr(
                    "test_results.finisher.test_result_notifier_error_comment",
                    tags={"status": success, "reason": reason},
                )

            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                QUEUE_NOTIFY_KEY: queue_notify,
            }

        # if we succeed once, error should be None for this commit forever
        if totals.error is not None:
            totals.error = None
            db_session.flush()

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

                if failure_message is not None:
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
            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                QUEUE_NOTIFY_KEY: True,
            }

        metrics.incr(
            "test_results.finisher",
            tags={"status": "success", "reason": "tests_failed"},
        )
        flaky_tests = None
        if FLAKY_TEST_DETECTION.check_value(identifier=repoid):
            flaky_tests = dict()

        failures = sorted(failures, key=lambda x: x.testsuite + x.testname)
        payload = TestResultsNotificationPayload(
            failed_tests, passed_tests, skipped_tests, failures, flaky_tests
        )

        with metrics.timing("test_results.finisher.notification"):
            checkpoints.log(TestResultsFlow.TEST_RESULTS_NOTIFY)
            # TODO: remove this later, we can do this now because there aren't many users using this
            metrics.distribution(
                "test_results_processing_time",
                checkpoints._subflow_duration(
                    TestResultsFlow.TEST_RESULTS_BEGIN,
                    TestResultsFlow.TEST_RESULTS_NOTIFY,
                ),
                unit="millisecond",
                tags={"repoid": repoid},
            )
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

        if FLAKY_TEST_DETECTION.check_value(identifier=repoid):
            log.info(
                "Running flaky test detection",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    commit_yaml=commit_yaml,
                    parent_task=self.request.parent_id,
                ),
            )
            with metrics.timing("test_results.finisher.run_flaky_test_detection"):
                success, reason = self.run_flaky_test_detection(
                    db_session, repoid, notifier, payload, checkpoints=checkpoints
                )

            metrics.incr(
                "test_results.finisher.flaky_test_detection",
                tags={"status": success, "reason": reason},
            )

        return {
            "notify_attempted": True,
            "notify_succeeded": success,
            QUEUE_NOTIFY_KEY: False,
        }

    def run_flaky_test_detection(
        self,
        db_session,
        repoid,
        notifier: TestResultsNotifier,
        payload: TestResultsNotificationPayload,
        checkpoints=None,
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
        unrelated_matches_detector = UnrelatedMatchesDetector(failure_normalizer)
        diff_outcome_detector = DiffOutcomeDetector()

        flake_detection_engine = FlakeDetectionEngine(
            db_session,
            repoid,
            [
                default_branch_failure_detector,
                unrelated_matches_detector,
                diff_outcome_detector,
            ],
        )

        log.info(
            "Starting flake detection",
            extra=dict(
                repoid=repoid,
                parent_task=self.request.parent_id,
            ),
        )
        current_state_of_repo_flakes = flake_detection_engine.detect_flakes()

        for test_id, symptoms in current_state_of_repo_flakes.items():
            log.info(
                "Discovered flaky test",
                extra=dict(
                    repoid=repoid,
                    parent_task=self.request.parent_id,
                    test_id=test_id,
                    symptoms=list(symptoms),
                ),
            )
            payload.flaky_tests[test_id] = TestResultsNotificationFlake(
                list(symptoms),
                True,
            )
            db_session.flush()

        if checkpoints:
            checkpoints.log(TestResultsFlow.FLAKE_DETECTION_NOTIFY)
            
            # TODO: remove this later, we can do this now because there aren't many users using this
            metrics.distribution(
                "test_results_processing_time",
                checkpoints._subflow_duration(
                    TestResultsFlow.TEST_RESULTS_NOTIFY,
                    TestResultsFlow.FLAKE_DETECTION_NOTIFY,
                ),
                unit="millisecond",
                tags={"repoid": repoid},
            )
        success, reason = async_to_sync(notifier.notify)(payload)
        log.info(
            "Added flaky test information to the PR comment",
            extra=dict(
                repoid=repoid,
                parent_task=self.request.parent_id,
                success=success,
                reason=reason,
            ),
        )

        return success, reason

    def get_flake_diff(
        self,
        newly_calculated_flakes: FlakeDetectionResult,
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
