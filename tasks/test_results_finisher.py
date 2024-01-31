import logging
from typing import Any, Dict

from shared.yaml import UserYaml
from sqlalchemy import desc
from test_results_parser import Outcome

from app import celery_app
from database.enums import ReportType
from database.models import Commit, CommitReport, Test, TestInstance, Upload
from services.lock_manager import LockManager, LockRetry, LockType
from services.test_results import TestResultsNotifier
from tasks.base import BaseCodecovTask
from tasks.notify import notify_task_name

log = logging.getLogger(__name__)

test_results_finisher_task_name = "app.tasks.test_results.TestResultsFinisherTask"


class TestResultsFinisherTask(BaseCodecovTask, name=test_results_finisher_task_name):
    async def run_async(
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
                return await self.process_async_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    previous_result=chord_result,
                    **kwargs,
                )
        except LockRetry as retry:
            self.retry(max_retries=5, countdown=retry.countdown)

    async def process_async_within_lock(
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
            return {"notify_attempted": False, "notify_succeeded": False}

        test_instances = (
            db_session.query(TestInstance)
            .join(Upload)
            .join(CommitReport)
            .join(Commit)
            .filter(Commit.id_ == commit.id_)
            .order_by(TestInstance.test_id)
            .order_by(desc(Upload.created_at))
            .distinct(TestInstance.test_id)
            .all()
        )

        if self.check_if_no_failures(test_instances):
            self.app.tasks[notify_task_name].apply_async(
                args=None,
                kwargs=dict(
                    repoid=repoid, commitid=commitid, current_yaml=commit_yaml.to_dict()
                ),
            )
            return {"notify_attempted": False, "notify_succeeded": False}

        success = None
        notifier = TestResultsNotifier(commit, commit_yaml, test_instances)
        success = await notifier.notify()

        log.info(
            "Finished test results notify",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                parent_task=self.request.parent_id,
            ),
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
            [instance.outcome != int(Outcome.Failure) for instance in testrun_list]
        )


RegisteredTestResultsFinisherTask = celery_app.register_task(TestResultsFinisherTask())
test_results_finisher_task = celery_app.tasks[RegisteredTestResultsFinisherTask.name]
