import logging
from datetime import datetime

from django.db import transaction
from django.db.models import Q, QuerySet
from redis.exceptions import LockError
from shared.django_apps.reports.models import CommitReport, ReportSession
from shared.django_apps.ta_timeseries.models import Testrun
from shared.django_apps.test_analytics.models import Flake
from shared.helpers.redis import get_redis_connection

from services.test_analytics.ta_metrics import process_flakes_summary

log = logging.getLogger(__name__)

FAIL_FILTER = Q(outcome="failure") | Q(outcome="flaky_failure") | Q(outcome="error")

LOCK_NAME = "ta_flake_lock:{}"
KEY_NAME = "ta_flake_key:{}"


def get_relevant_uploads(repo_id: int, commit_id: str) -> QuerySet[ReportSession]:
    return ReportSession.objects.filter(
        report__report_type=CommitReport.ReportType.TEST_RESULTS.value,
        report__commit__repository__repoid=repo_id,
        report__commit__commitid=commit_id,
        state__in=["processed"],
    )


def fetch_current_flakes(repo_id: int) -> dict[bytes, Flake]:
    return {
        bytes(flake.test_id): flake for flake in Flake.objects.filter(repoid=repo_id)
    }


def get_testruns(
    upload: ReportSession, curr_flakes: dict[bytes, Flake]
) -> QuerySet[Testrun]:
    upload_filter = Q(upload_id=upload.id)
    flaky_pass_filter = Q(outcome="pass") & Q(test_id__in=curr_flakes.keys())
    return Testrun.objects.filter(upload_filter & (FAIL_FILTER | flaky_pass_filter))


def handle_pass(curr_flakes: dict[bytes, Flake], test_id: bytes):
    # possible that we expire it and stop caring about it
    if test_id not in curr_flakes:
        return

    curr_flakes[test_id].recent_passes_count += 1
    curr_flakes[test_id].count += 1
    if curr_flakes[test_id].recent_passes_count == 30:
        curr_flakes[test_id].end_date = datetime.now()
        curr_flakes[test_id].save()
        del curr_flakes[test_id]


def handle_failure(
    curr_flakes: dict[bytes, Flake], test_id: bytes, testrun: Testrun, repo_id: int
):
    existing_flake = curr_flakes.get(test_id)
    if existing_flake:
        existing_flake.fail_count += 1
        existing_flake.count += 1
        existing_flake.recent_passes_count = 0
    else:
        if testrun.outcome != "flaky_failure":
            testrun.outcome = "flaky_failure"
        new_flake = Flake(
            repoid=repo_id,
            test_id=test_id,
            count=1,
            fail_count=1,
            recent_passes_count=0,
            start_date=datetime.now(),
        )
        curr_flakes[test_id] = new_flake


@process_flakes_summary.labels("new").time()
def process_flakes_for_commit(repo_id: int, commit_id: str):
    uploads = get_relevant_uploads(repo_id, commit_id)

    curr_flakes = fetch_current_flakes(repo_id)

    for upload in uploads:
        testruns = get_testruns(upload, curr_flakes)

        for testrun in testruns:
            test_id = bytes(testrun.test_id)
            match testrun.outcome:
                case "pass":
                    handle_pass(curr_flakes, test_id)
                case "failure" | "flaky_failure" | "error":
                    handle_failure(curr_flakes, test_id, testrun, repo_id)
                case _:
                    continue

        Testrun.objects.bulk_update(testruns, ["outcome"])

    Flake.objects.bulk_create(
        curr_flakes.values(),
        update_conflicts=True,
        unique_fields=["id"],
        update_fields=["end_date", "count", "recent_passes_count", "fail_count"],
    )

    transaction.commit()


def process_flakes_for_repo(repo_id: int):
    redis_client = get_redis_connection()
    lock_name = LOCK_NAME.format(repo_id)
    key_name = KEY_NAME.format(repo_id)
    try:
        with redis_client.lock(lock_name, timeout=300, blocking_timeout=3):
            while commit_ids := redis_client.lpop(key_name, 10):
                for commit_id in commit_ids:
                    process_flakes_for_commit(repo_id, commit_id.decode())
            return True
    except LockError:
        log.warning("Failed to acquire lock for repo %s", repo_id)
        return False
