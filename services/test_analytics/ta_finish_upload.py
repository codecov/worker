import logging
from typing import Literal

import sentry_sdk
from asgiref.sync import async_to_sync
from shared.celery_config import cache_test_rollups_task_name, process_flakes_task_name
from shared.django_apps.reports.models import ReportSession, UploadError
from shared.helpers.redis import get_redis_connection
from shared.reports.types import UploadType
from shared.typings.torngit import AdditionalData
from shared.yaml import UserYaml
from sqlalchemy.orm import Session

from app import celery_app
from database.models import Commit, Repository
from helpers.notifier import NotifierResult
from helpers.string import shorten_file_paths
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.seats import check_seat_activation
from services.test_analytics.ta_metrics import (
    read_failures_summary,
    read_tests_totals_summary,
)
from services.test_analytics.ta_process_flakes import KEY_NAME
from services.test_analytics.ta_timeseries import (
    TestInstance,
    get_flaky_tests_dict,
    get_pr_comment_agg,
    get_pr_comment_failures,
)
from services.test_results import (
    ErrorPayload,
    FinisherResult,
    TACommentInDepthInfo,
    TestResultsNotificationFailure,
    TestResultsNotificationPayload,
    TestResultsNotifier,
    should_do_flaky_detection,
)

log = logging.getLogger(__name__)


def get_relevant_upload_ids(commitid: str) -> dict[int, ReportSession]:
    return {
        upload.id: upload
        for upload in ReportSession.objects.filter(
            report__commit__commitid=commitid,
            state__in=["processed", "finished", "flake_processed"],
        )
    }


def get_upload_error(upload_ids: list[int]) -> ErrorPayload | None:
    error = (
        UploadError.objects.filter(report_session_id__in=upload_ids)
        .order_by("created_at")
        .first()
    )
    if error:
        return ErrorPayload(
            error_code=error.error_code,
            error_message=error.error_params.get("error_message"),
        )
    return None


def transform_failures(
    uploads: dict[int, ReportSession], failures: list[TestInstance]
) -> list[TestResultsNotificationFailure[bytes]]:
    notif_failures = []
    for failure in failures:
        if failure["failure_message"] is not None:
            failure["failure_message"] = shorten_file_paths(
                failure["failure_message"]
            ).replace("\r", "")

        notif_failures.append(
            TestResultsNotificationFailure(
                display_name=failure["computed_name"],
                failure_message=failure["failure_message"],
                test_id=failure["test_id"],
                envs=uploads[failure["upload_id"]].flag_names,
                duration_seconds=failure["duration_seconds"] or 0,
                build_url=uploads[failure["upload_id"]].build_url,
            )
        )
    return notif_failures


def queue_followup_tasks(
    repo: Repository,
    commit: Commit,
    commit_yaml: UserYaml,
    impl_type: Literal["new", "both"] = "both",
):
    if (
        should_do_flaky_detection(repo, commit_yaml)
        and commit.merged is True
        and commit.branch == repo.branch
    ):
        redis_client = get_redis_connection()
        redis_client.set(f"flake_uploads:{repo.repoid}", 0)
        redis_client.lpush(KEY_NAME.format(repo.repoid), commit.commitid)

        celery_app.send_task(
            process_flakes_task_name,
            kwargs={
                "repo_id": repo.repoid,
                "commit_id": commit.commitid,
                "impl_type": impl_type,
            },
        )

    if commit.branch is not None:
        celery_app.send_task(
            cache_test_rollups_task_name,
            kwargs={
                "repoid": repo.repoid,
                "branch": commit.branch,
                "impl_type": impl_type,
            },
        )


@sentry_sdk.trace
def new_impl(
    db_session: Session,  # only used for seat activation, for now
    repo: Repository,  # using sqlalchemy models for now
    commit: Commit,
    commit_yaml: UserYaml,
    impl_type: Literal["new", "both"] = "both",
) -> FinisherResult:
    repoid = repo.repoid
    commitid = commit.commitid

    extra = {
        "repo_id": repoid,
        "commit_id": commitid,
        "impl_type": impl_type,
    }

    log.info("Starting new_impl of TA finisher", extra=extra)

    queue_followup_tasks(repo, commit, commit_yaml, impl_type)

    if not commit_yaml.read_yaml_field("comment", _else=True):
        log.info("Comment is disabled, not posting comment", extra=extra)
        return {
            "notify_attempted": False,
            "notify_succeeded": False,
            "queue_notify": False,
        }

    upload_ids = get_relevant_upload_ids(commitid)
    error = get_upload_error(list(upload_ids.keys()))

    with read_tests_totals_summary.labels(impl="new").time():
        summary = get_pr_comment_agg(repoid, commitid)

    if not summary["failed"] and error is None:
        log.info(
            "No failures and no error so not posting comment but still queueing notify",
            extra=extra,
        )
        return {
            "notify_attempted": False,
            "notify_succeeded": True,
            "queue_notify": True,
        }

    additional_data: AdditionalData = {"upload_type": UploadType.TEST_RESULTS}
    repo_service = get_repo_provider_service(repo, additional_data=additional_data)
    pull = async_to_sync(fetch_and_update_pull_request_information_from_commit)(
        repo_service, commit, commit_yaml
    )

    if not pull:
        log.info("No pull so not posting comment", extra=extra)
        return {
            "notify_attempted": False,
            "notify_succeeded": False,
            "queue_notify": False,
        }

    notifier = TestResultsNotifier(
        commit,
        commit_yaml,
        _pull=pull,
        _repo_service=repo_service,
        error=error,
    )

    seat_needs_activation = check_seat_activation(db_session, pull)

    if seat_needs_activation:
        success, _ = notifier.upgrade_comment()
        log.info(
            "Seat needs activation, posted upgrade comment",
            extra={**extra, "success": success},
        )
        return {
            "notify_attempted": False,
            "notify_succeeded": success,
            "queue_notify": False,
        }

    if summary["failed"] == 0:
        # no failures, only error
        log.info("No failures, posting error comment", extra=extra)
        notifier.error_comment()

        return {
            "notify_attempted": True,
            "notify_succeeded": False,
            "queue_notify": True,
        }

    with read_failures_summary.labels(impl="new").time():
        failures = get_pr_comment_failures(repoid, commitid)

    notif_failures = transform_failures(upload_ids, failures)

    flaky_tests = dict()

    # flake detection if appropriate
    if should_do_flaky_detection(repo, commit_yaml):
        flaky_tests = get_flaky_tests_dict(repoid)

    payload = TestResultsNotificationPayload(
        failed=summary["failed"],
        passed=summary["passed"],
        skipped=summary["skipped"],
        info=TACommentInDepthInfo(notif_failures, flaky_tests),
    )

    notifier.payload = payload

    notifier_result = notifier.notify()
    success = True if notifier_result is NotifierResult.COMMENT_POSTED else False
    log.info("Posted TA comment", extra={**extra, "success": success})
    return {
        "notify_attempted": True,
        "notify_succeeded": success,
        "queue_notify": False,
    }
