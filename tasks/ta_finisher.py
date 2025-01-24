import logging
from dataclasses import dataclass
from typing import Any

from asgiref.sync import async_to_sync
from shared.reports.types import UploadType
from shared.typings.torngit import AdditionalData
from shared.yaml import UserYaml
from sqlalchemy.orm import Session

from app import celery_app
from database.enums import FlakeSymptomType, ReportType
from database.models import (
    Commit,
    CommitReport,
    Repository,
    TestResultReportTotals,
    Upload,
    UploadError,
)
from django_scaffold.settings import BIGQUERY_READ_ENABLED
from helpers.checkpoint_logger.flows import TestResultsFlow
from helpers.notifier import NotifierResult
from helpers.string import EscapeEnum, Replacement, StringEscaper, shorten_file_paths
from services.activation import activate_user
from services.lock_manager import LockManager, LockRetry, LockType
from services.redis import get_redis_connection
from services.repository import (
    EnrichedPull,
    TorngitBaseAdapter,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.seats import ShouldActivateSeat, determine_seat_activation
from services.ta_utils import (
    FlakeInfo,
    TestFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    should_do_flaky_detection,
)
from ta_storage.base import PRCommentAggResult, PRCommentFailResult
from ta_storage.bq import BQDriver
from ta_storage.pg import PGDriver
from tasks.base import BaseCodecovTask
from tasks.notify import notify_task
from tasks.ta_cache_analytics import ta_cache_analytics_task
from tasks.ta_process_flakes import TA_FLAKE_UPLOADS_KEY, ta_process_flakes_task

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


def get_uploads(db_session: Session, commit: Commit) -> dict[int, Upload]:
    return {
        upload.id: upload
        for upload in (
            db_session.query(Upload)
            .join(CommitReport)
            .filter(
                CommitReport.commit_id == commit.id,
                CommitReport.report_type == ReportType.TEST_RESULTS.value,
                Upload.state.in_(["v2_processed", "v2_finished"]),
            )
            .all()
        )
    }


def queue_optional_tasks(
    repo: Repository,
    commit: Commit,
    commit_yaml: UserYaml,
    branch: str | None,
):
    redis_client = get_redis_connection()
    if should_do_flaky_detection(repo, commit_yaml):
        if commit.merged is True or branch == repo.branch:
            # run new process flakes task
            redis_client.set(TA_FLAKE_UPLOADS_KEY.format(repo_id=repo.repoid), 0)
            ta_process_flakes_task_sig = ta_process_flakes_task.s(
                repo_id=repo.repoid,
                commit_id=commit.commitid,
            )
            ta_process_flakes_task_sig.apply_async()

    if branch is not None:
        cache_task_sig = ta_cache_analytics_task.s(
            repoid=repo.repoid,
            branch=branch,
        )
        cache_task_sig.apply_async()


def get_totals(
    commit_report: CommitReport, db_session: Session
) -> TestResultReportTotals:
    totals = commit_report.test_result_totals
    if totals is None:
        totals = TestResultReportTotals()
        totals.report = commit_report
        totals.passed = 0
        totals.skipped = 0
        totals.failed = 0
        db_session.add(totals)
        db_session.flush()

    return totals


def get_bigquery_test_data(
    repo: Repository, commit_sha: str, commit_yaml: UserYaml
) -> tuple[
    PRCommentAggResult,
    list[PRCommentFailResult[tuple[bytes, bytes | None]]],
    dict[tuple[bytes, bytes | None], FlakeInfo] | None,
]:
    driver = BQDriver(repo.repoid)
    agg_result = driver.pr_comment_agg(commit_sha)
    failures = driver.pr_comment_fail(commit_sha)
    if should_do_flaky_detection(repo, commit_yaml):
        flaky_tests = driver.get_repo_flakes(
            tuple(failure["id"] for failure in failures)
        )
    else:
        flaky_tests = None

    return agg_result, failures, flaky_tests


def get_postgres_test_data(
    db_session: Session, repo: Repository, commit_sha: str, commit_yaml: UserYaml
) -> tuple[
    PRCommentAggResult, list[PRCommentFailResult[str]], dict[str, FlakeInfo] | None
]:
    driver = PGDriver(repo.repoid, db_session)
    agg_result = driver.pr_comment_agg(commit_sha)
    failures = driver.pr_comment_fail(commit_sha)
    if should_do_flaky_detection(repo, commit_yaml):
        flaky_tests = driver.get_repo_flakes(
            tuple(failure["id"] for failure in failures)
        )
    else:
        flaky_tests = None

    return agg_result, failures, flaky_tests


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
                    **kwargs,
                )
            if finisher_result["queue_notify"]:
                notify_task_sig = notify_task.s(
                    repoid=repoid,
                    commitid=commitid,
                    current_yaml=commit_yaml,
                )
                notify_task_sig.apply_async()

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
        **kwargs,
    ):
        log.info("Running test results finishers", extra=self.extra_dict)
        TestResultsFlow.log(TestResultsFlow.TEST_RESULTS_FINISHER_BEGIN)

        commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        if commit is None:
            raise ValueError("commit not found")

        commit_report = commit.commit_report(ReportType.TEST_RESULTS)

        uploads = get_uploads(db_session, commit)

        repo = commit.repository
        branch = commit.branch

        if BIGQUERY_READ_ENABLED:
            agg_result, failures, flaky_tests = get_bigquery_test_data(
                repo, commitid, commit_yaml
            )
            payload = TestResultsNotificationPayload(
                agg_result["failed_ct"] + agg_result["flaky_failed_ct"],
                agg_result["passed_ct"],
                agg_result["skipped_ct"],
            )

            if failures:
                escaper = StringEscaper(ESCAPE_FAILURE_MESSAGE_DEFN)
                shorten_paths = commit_yaml.read_yaml_field(
                    "test_analytics", "shorten_paths", _else=True
                )

                failures_list = []
                flaky_failures = []

                for failure in failures:
                    failure_message = failure["failure_message"]
                    if failure_message is not None and shorten_paths:
                        failure_message = shorten_file_paths(failure_message)
                    if failure_message is not None:
                        failure_message = escaper.replace(failure_message)

                    test_id = failure["id"]
                    base_failure = TestFailure(
                        display_name=failure["computed_name"],
                        failure_message=failure_message,
                        duration_seconds=failure["duration_seconds"],
                        build_url=uploads[failure["upload_id"]].build_url
                        if failure["upload_id"] in uploads
                        else None,
                    )

                    if flaky_tests and test_id in flaky_tests:
                        flaky_failures.append(
                            TestFailure(
                                display_name=base_failure.display_name,
                                failure_message=base_failure.failure_message,
                                duration_seconds=base_failure.duration_seconds,
                                build_url=base_failure.build_url,
                                flake_info=flaky_tests[test_id],
                            )
                        )
                    else:
                        failures_list.append(base_failure)

                failures_list = sorted(failures_list, key=lambda x: x.duration_seconds)
                flaky_failures = sorted(
                    flaky_failures, key=lambda x: x.duration_seconds
                )

                payload.regular_failures = failures_list if failures_list else None
                payload.flaky_failures = flaky_failures if flaky_failures else None
        else:
            totals = get_totals(commit_report, db_session)

            agg_result, failures, flaky_tests = get_postgres_test_data(
                db_session, repo, commitid, commit_yaml
            )

            totals.failed = agg_result["failed_ct"]
            totals.skipped = agg_result["skipped_ct"]
            totals.passed = agg_result["passed_ct"]
            db_session.flush()

            payload = TestResultsNotificationPayload(
                totals.failed, totals.passed, totals.skipped
            )

            if failures:
                escaper = StringEscaper(ESCAPE_FAILURE_MESSAGE_DEFN)
                shorten_paths = commit_yaml.read_yaml_field(
                    "test_analytics", "shorten_paths", _else=True
                )

                failures_list = []
                flaky_failures = []

                for failure in failures:
                    failure_message = failure["failure_message"]
                    if failure_message is not None and shorten_paths:
                        failure_message = shorten_file_paths(failure_message)
                    if failure_message is not None:
                        failure_message = escaper.replace(failure_message)

                    test_id = failure["id"]
                    base_failure = TestFailure(
                        display_name=failure["computed_name"],
                        failure_message=failure_message,
                        duration_seconds=failure["duration_seconds"],
                        build_url=uploads[failure["upload_id"]].build_url
                        if failure["upload_id"] in uploads
                        else None,
                    )

                    if flaky_tests and test_id in flaky_tests:
                        flaky_failures.append(
                            TestFailure(
                                display_name=base_failure.display_name,
                                failure_message=base_failure.failure_message,
                                duration_seconds=base_failure.duration_seconds,
                                build_url=base_failure.build_url,
                                flake_info=flaky_tests[test_id],
                            )
                        )
                    else:
                        failures_list.append(base_failure)

                failures_list = sorted(failures_list, key=lambda x: x.duration_seconds)
                flaky_failures = sorted(
                    flaky_failures, key=lambda x: x.duration_seconds
                )

                if failures_list or flaky_failures:
                    payload = TestResultsNotificationPayload(
                        totals.failed,
                        totals.passed,
                        totals.skipped,
                        regular_failures=failures_list if failures_list else None,
                        flaky_failures=flaky_failures if flaky_failures else None,
                    )

        additional_data: AdditionalData = {"upload_type": UploadType.TEST_RESULTS}
        repo_service = get_repo_provider_service(repo, additional_data=additional_data)
        pull = async_to_sync(fetch_and_update_pull_request_information_from_commit)(
            repo_service, commit, commit_yaml
        )

        if pull:
            seat_activation_result = self.seat_activation(
                db_session, pull, commit, commit_yaml, repo_service
            )
            if seat_activation_result:
                return seat_activation_result

        upload_error = (
            db_session.query(UploadError)
            .filter(UploadError.upload_id.in_(uploads.keys()))
            .first()
        )

        if not (payload or upload_error):
            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                "queue_notify": True,
            }

        notifier = TestResultsNotifier(
            commit,
            commit_yaml,
            payload=payload,
            _pull=pull,
            _repo_service=repo_service,
            error=upload_error,
        )
        notifier_result = notifier.notify()

        for upload in uploads.values():
            upload.state = "v2_finished"
        db_session.commit()

        queue_optional_tasks(repo, commit, commit_yaml, branch)

        success = True if notifier_result is NotifierResult.COMMENT_POSTED else False
        TestResultsFlow.log(TestResultsFlow.TEST_RESULTS_NOTIFY)

        self.extra_dict["success"] = success
        self.extra_dict["notifier_result"] = notifier_result.value
        log.info("Finished test results notify", extra=self.extra_dict)

        return {
            "notify_attempted": True,
            "notify_succeeded": success,
            "queue_notify": not payload,
        }

    def seat_activation(
        self,
        db_session: Session,
        pull: EnrichedPull,
        commit: Commit,
        commit_yaml: UserYaml,
        repo_service: TorngitBaseAdapter,
    ) -> dict[str, bool] | None:
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


RegisteredTAFinisherTask = celery_app.register_task(TAFinisherTask())
ta_finisher_task = celery_app.tasks[RegisteredTAFinisherTask.name]
