import logging
from dataclasses import dataclass
from typing import Any

from asgiref.sync import async_to_sync
from shared.yaml import UserYaml
from sqlalchemy.orm import Session
from test_results_parser import Outcome

from app import celery_app
from database.enums import FlakeSymptomType, ReportType, TestResultsProcessingError
from database.models import Commit, Flake, Repository, TestResultReportTotals
from helpers.checkpoint_logger.flows import TestResultsFlow
from helpers.metrics import metrics
from helpers.notifier import NotifierResult
from helpers.string import EscapeEnum, Replacement, StringEscaper, shorten_file_paths
from services.activation import activate_user
from services.lock_manager import LockManager, LockRetry, LockType
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
    latest_test_instances_for_a_given_commit,
    should_do_flaky_detection,
)
from tasks.base import BaseCodecovTask
from tasks.cache_test_rollups import cache_test_rollups_task_name
from tasks.notify import notify_task_name
from tasks.process_flakes import process_flakes_task_name

log = logging.getLogger(__name__)

test_results_finisher_task_name = "app.tasks.test_results.TestResultsFinisherTask"

ESCAPE_FAILURE_MESSAGE_DEFN = [
    Replacement(["\r"], "", EscapeEnum.REPLACE),
]


@dataclass
class FlakeUpdateInfo:
    new_flake_ids: list[str]
    old_flake_ids: list[str]
    newly_calculated_flakes: dict[str, set[FlakeSymptomType]]


class TestResultsFinisherTask(BaseCodecovTask, name=test_results_finisher_task_name):
    def run_impl(
        self,
        db_session: Session,
        chord_result: dict[str, Any],
        *,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        **kwargs,
    ):
        repoid = int(repoid)
        commit_yaml = UserYaml.from_dict(commit_yaml)

        self.extra_dict = {
            "repoid": repoid,
            "commit": commitid,
            "commit_yaml": commit_yaml,
        }

        log.info(
            "Starting test results finisher task",
            extra=self.extra_dict,
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
            if finisher_result["queue_notify"]:
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
        db_session: Session,
        repoid: int,
        commitid: str,
        commit_yaml: UserYaml,
        previous_result: dict[str, Any],
        **kwargs,
    ):
        log.info(
            "Running test results finishers",
            extra=self.extra_dict,
        )

        TestResultsFlow.log(TestResultsFlow.TEST_RESULTS_FINISHER_BEGIN)

        commit: Commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )

        assert commit, "commit not found"

        repo = db_session.query(Repository).filter_by(repoid=repoid).first()
        if should_do_flaky_detection(repo, commit_yaml):
            if commit.merged is True or commit.branch == repo.branch:
                self.app.tasks[process_flakes_task_name].apply_async(
                    kwargs=dict(
                        repo_id=repoid,
                        commit_id_list=[commit.commitid],
                        branch=repo.branch,
                    )
                )

        self.app.tasks[cache_test_rollups_task_name].apply_async(
            args=None,
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

        with metrics.timer("test_results.finisher.fetch_latest_test_instances"):
            test_instances = latest_test_instances_for_a_given_commit(
                db_session, commit.id_
            )

        if self.check_if_no_success(previous_result):
            # every processor errored, nothing to notify on
            metrics.incr("test_results.finisher.failure.no_successful_processing")

            queue_notify = False

            # if error is None this whole process should be a noop
            if totals.error is not None:
                # make an attempt to make test results comment
                notifier = TestResultsNotifier(commit, commit_yaml, None)

                success, reason = notifier.error_comment()

                # also make attempt to make coverage comment
                queue_notify = True

                metrics.incr(
                    f"test_results.finisher.test_result_notifier_error_comment.{"successful" if success else "failure"}.{reason}",
                )

            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                "queue_notify": queue_notify,
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

                build_url = test_instance.upload.build_url

                failures.append(
                    TestResultsNotificationFailure(
                        display_name=test_instance.test.computed_name
                        if test_instance.test.computed_name is not None
                        else test_instance.test.name,
                        failure_message=failure_message,
                        test_id=test_instance.test_id,
                        envs=flag_names,
                        duration_seconds=test_instance.duration_seconds,
                        build_url=build_url,
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
            metrics.incr("test_results.finisher.normal_notify_called.all_tests_passed")
            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                "queue_notify": True,
            }

        metrics.incr("test_results.finisher.success.tests_failed")
        repo_service = get_repo_provider_service(repo)
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
                notifier = TestResultsNotifier(commit, commit_yaml, pull)

                success, reason = notifier.upgrade_comment()

                metrics.incr(
                    f"test_results.finisher.test_result_notifier_upgrade_comment.{"success" if success else "failure"}.{reason}",
                )

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
            failed_tests,
            passed_tests,
            skipped_tests,
            failures,
            flaky_tests,
        )

        notifier = TestResultsNotifier(commit, commit_yaml, payload=payload)

        with metrics.timer("test_results.finisher.notification"):
            TestResultsFlow.log(TestResultsFlow.TEST_RESULTS_NOTIFY)

            if begin_to_notify := TestResultsFlow._subflow_duration(
                TestResultsFlow.TEST_RESULTS_BEGIN,
                TestResultsFlow.TEST_RESULTS_NOTIFY,
                data=TestResultsFlow._data_from_log_context(),
            ):
                metrics.timing(
                    f"test_results_notif_latency.{"flaky" if should_do_flaky_detection(repo, commit_yaml) else "non_flaky"}",
                    begin_to_notify,
                )
            notifier_result: NotifierResult = notifier.notify()

        match notifier_result:
            case NotifierResult.COMMENT_POSTED:
                success = True
            case _:
                success = False

        if len(flaky_tests):
            log.info(
                "Detected failure on test that has been identified as flaky",
                extra=dict(
                    success=success,
                    notifier_result=notifier_result.value,
                    test_ids=list(flaky_tests.keys()),
                ),
            )
            metrics.incr("test_results.finisher.detected_flaky_test")

        self.extra_dict["success"] = success
        self.extra_dict["notifier_result"] = notifier_result.value
        log.info("Finished test results notify", extra=self.extra_dict)

        # using a var as a tag here will be fine as it's a boolean
        metrics.incr(
            f"test_results.finisher.test_result_notifier.{"success" if success else "failure"}.{notifier_result.value}",
        )

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
