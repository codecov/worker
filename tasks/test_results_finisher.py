import logging
from typing import Any, Dict

from asgiref.sync import async_to_sync
from sentry_sdk import metrics
from shared.yaml import UserYaml
from test_results_parser import Outcome

from app import celery_app
from database.enums import ReportType
from database.models import Commit, CommitReport, Test, TestInstance, Upload
from services.lock_manager import LockManager, LockRetry, LockType
from services.test_results import (
    TestResultsNotifier,
    latest_test_instances_for_a_given_commit,
)
from tasks.base import BaseCodecovTask
from tasks.notify import notify_task_name

log = logging.getLogger(__name__)

test_results_finisher_task_name = "app.tasks.test_results.TestResultsFinisherTask"


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
                tags={"status": "failure", "reason": "no_success"},
            )
            return {"notify_attempted": False, "notify_succeeded": False}

        with metrics.timing("test_results.finisher.fetch_latest_test_instances"):
            test_instances = latest_test_instances_for_a_given_commit(
                db_session, commit.id_
            )

        if self.check_if_no_failures(test_instances):
            metrics.incr(
                "test_results.finisher",
                tags={"status": "success", "reason": "no_failures"},
            )
            self.app.tasks[notify_task_name].apply_async(
                args=None,
                kwargs=dict(
                    repoid=repoid, commitid=commitid, current_yaml=commit_yaml.to_dict()
                ),
            )
            return {"notify_attempted": False, "notify_succeeded": False}

        metrics.incr("test_results.finisher", tags={"status": "failures_exist"})

        notifier = TestResultsNotifier(commit, commit_yaml, test_instances)
        with metrics.timing("test_results.finisher.notification"):
            success = async_to_sync(notifier.notify)()

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
            "test_results.finisher",
            tags={"status": success, "reason": "notified"},
        )
        return {"notify_attempted": True, "notify_succeeded": success}

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
