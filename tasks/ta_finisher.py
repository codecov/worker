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
    Flake,
    Repository,
    TestResultReportTotals,
    Upload,
    UploadError,
)
from helpers.checkpoint_logger.flows import TestResultsFlow
from helpers.notifier import NotifierResult
from helpers.string import EscapeEnum, Replacement, StringEscaper, shorten_file_paths
from services.activation import activate_user, schedule_new_user_activated_task
from services.lock_manager import LockManager, LockRetry, LockType
from services.redis import get_redis_connection
from services.repository import (
    EnrichedPull,
    TorngitBaseAdapter,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.seats import ShouldActivateSeat, determine_seat_activation
from services.test_results import (
    FlakeInfo,
    TACommentInDepthInfo,
    TestResultsNotificationFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    get_test_summary_for_commit,
    latest_failures_for_commit,
    should_do_flaky_detection,
)
from tasks.base import BaseCodecovTask
from tasks.cache_test_rollups import cache_test_rollups_task
from tasks.notify import notify_task
from tasks.process_flakes import (
    NEW_KEY,
    process_flakes_task,
)

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
            redis_client.rpush(NEW_KEY.format(repo.repoid), commit.commitid)
            process_flakes_task_sig = process_flakes_task.s(
                repo_id=repo.repoid,
                commit_id=commit.commitid,
            )
            process_flakes_task_sig.apply_async()

    if branch is not None:
        cache_task_sig = cache_test_rollups_task.s(
            repoid=repo.repoid,
            branch=branch,
        )
        cache_task_sig.apply_async()


def get_totals(
    commit_report: CommitReport, db_session: Session
) -> TestResultReportTotals:
    totals = commit_report.test_result_totals
    if totals is None:
        totals = TestResultReportTotals(
            report_id=commit_report.id,
        )
        totals.passed = 0
        totals.skipped = 0
        totals.failed = 0
        db_session.add(totals)
        db_session.flush()

    return totals


def populate_failures(
    failures: list[TestResultsNotificationFailure],
    db_session: Session,
    repoid: int,
    commitid: str,
    shorten_paths: bool,
    uploads: dict[int, Upload],
    escaper: StringEscaper,
) -> None:
    failed_test_instances = latest_failures_for_commit(db_session, repoid, commitid)

    for test_instance in failed_test_instances:
        failure_message = test_instance.failure_message
        if failure_message is not None:
            if shorten_paths:
                failure_message = shorten_file_paths(failure_message)
            failure_message = escaper.replace(failure_message)

        upload = uploads[test_instance.upload_id]

        failures.append(
            TestResultsNotificationFailure(
                display_name=test_instance.test.computed_name
                if test_instance.test.computed_name is not None
                else test_instance.test.name,
                failure_message=failure_message,
                test_id=test_instance.test_id,
                envs=upload.flag_names,
                duration_seconds=test_instance.duration_seconds,
                build_url=upload.build_url,
            )
        )


def get_flaky_tests(
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

        commit: Commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        assert commit, "commit not found"

        commit_report = commit.commit_report(ReportType.TEST_RESULTS)

        totals = get_totals(commit_report, db_session)
        uploads = get_uploads(
            db_session, commit
        )  # processed uploads that have yet to be persisted

        repo = commit.repository
        branch = commit.branch

        uploads = get_uploads(db_session, commit)

        # if we succeed once, error should be None for this commit forever
        if totals.error is not None:
            totals.error = None
            db_session.flush()

        test_summary = get_test_summary_for_commit(db_session, repoid, commitid)
        totals.failed = test_summary.get("error", 0) + test_summary.get("failure", 0)
        totals.skipped = test_summary.get("skip", 0)
        totals.passed = test_summary.get("pass", 0)
        db_session.flush()

        info = None
        if totals.failed:
            escaper = StringEscaper(ESCAPE_FAILURE_MESSAGE_DEFN)
            shorten_paths = commit_yaml.read_yaml_field(
                "test_analytics", "shorten_paths", _else=True
            )

            failures = []
            populate_failures(
                failures,
                db_session,
                repoid,
                commitid,
                shorten_paths,
                uploads,
                escaper,
            )

            flaky_tests = dict()
            if should_do_flaky_detection(repo, commit_yaml):
                flaky_tests = get_flaky_tests(db_session, repoid, failures)

            failures = sorted(failures, key=lambda x: x.duration_seconds)[:3]

            info = TACommentInDepthInfo(failures, flaky_tests)

        additional_data: AdditionalData = {"upload_type": UploadType.TEST_RESULTS}
        repo_service = get_repo_provider_service(repo, additional_data=additional_data)
        pull = async_to_sync(fetch_and_update_pull_request_information_from_commit)(
            repo_service, commit, commit_yaml
        )

        upload_error = (
            db_session.query(UploadError)
            .filter(UploadError.upload_id.in_(uploads.keys()))
            .first()
        )

        if not (info or upload_error):
            return {
                "notify_attempted": False,
                "notify_succeeded": False,
                "queue_notify": True,
            }

        if not pull:
            success = False
            notifier_result = NotifierResult.NO_PULL
        elif not commit_yaml.read_yaml_field("comment", _else=True):
            success = False
            notifier_result = NotifierResult.NO_COMMENT
        else:
            seat_activation_result = self.seat_activation(
                db_session, pull, commit, commit_yaml, repo_service
            )
            if seat_activation_result:
                return seat_activation_result

            payload = TestResultsNotificationPayload(
                totals.failed, totals.passed, totals.skipped, info
            )
            notifier = TestResultsNotifier(
                commit,
                commit_yaml,
                payload=payload,
                _pull=pull,
                _repo_service=repo_service,
                error=upload_error,
            )
            notifier_result = notifier.notify()

            success = (
                True if notifier_result is NotifierResult.COMMENT_POSTED else False
            )
            TestResultsFlow.log(TestResultsFlow.TEST_RESULTS_NOTIFY)

        self.extra_dict["success"] = success
        self.extra_dict["notifier_result"] = notifier_result.value

        for upload in uploads.values():
            upload.state = "v2_finished"
        db_session.commit()

        queue_optional_tasks(repo, commit, commit_yaml, branch)

        log.info("Finished test results notify", extra=self.extra_dict)

        return {
            "notify_attempted": notifier_result is NotifierResult.COMMENT_POSTED,
            "notify_succeeded": success,
            "queue_notify": not info,
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
                    schedule_new_user_activated_task(
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
