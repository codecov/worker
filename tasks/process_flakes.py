import logging
from typing import Any

from django.db import transaction as django_transaction
from django.db.models import Q
from shared.celery_config import process_flakes_task_name
from shared.django_apps.reports.models import (
    CommitReport,
    DailyTestRollup,
    Flake,
    ReportSession,
    TestInstance,
)

from app import celery_app
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


FLAKE_EXPIRY_COUNT = 30


class ProcessFlakesTask(BaseCodecovTask, name=process_flakes_task_name):
    """
    This task is currently called in the test results finisher task and in the sync pulls task
    """

    def run_impl(
        self,
        _db_session: Any,
        *,
        repo_id: int,
        commit_id: str,
        **kwargs: Any,
    ):
        """
        This task wants to iterate through uploads for a given commit that have yet to be
        "flake processed".

        For each of those uploads it wants to iterate through its test instances and
        update existing flakes' count, recent_passes_count, fail_count, and end_date fields
        depending on whether the test instance passed or failed.

        For each upload it wants to keep track of newly created flakes and keep those in a separate
        collection than the existing flakes, so at the end it can bulk create the new flakes and
        bulk update the existing flakes.

        It also wants to increment the flaky_fail_count of the relevant DailyTestRollup when it creates
        a new flake so it keeps track of those changes and bulk updates those as well.

        When it's done with an upload it merges the new flakes dictionary into the existing flakes dictionary
        and then clears the new flakes dictionary so the following upload considers the flakes created during the previous
        iteration as existing.
        """
        log.info(
            "Received process flakes task",
            extra=dict(repoid=repo_id, commit=commit_id),
        )

        uploads = ReportSession.objects.filter(
            report__report_type=CommitReport.ReportType.TEST_RESULTS.value,
            report__commit__commitid=commit_id,
            state="processed",
        ).all()

        curr_flakes = fetch_curr_flakes(repo_id)
        new_flakes: dict[str, Flake] = dict()

        rollups_to_update: list[DailyTestRollup] = []

        flaky_tests = list(curr_flakes.keys())

        for upload in uploads:
            test_instances = get_test_instances(upload, flaky_tests)
            for test_instance in test_instances:
                if test_instance.outcome == TestInstance.Outcome.PASS.value:
                    flake = new_flakes.get(test_instance.test_id) or curr_flakes.get(
                        test_instance.test_id
                    )
                    if flake is not None:
                        update_flake(flake, test_instance)
                elif test_instance.outcome in (
                    TestInstance.Outcome.FAILURE.value,
                    TestInstance.Outcome.ERROR.value,
                ):
                    flake = new_flakes.get(test_instance.test_id) or curr_flakes.get(
                        test_instance.test_id
                    )
                    if flake:
                        update_flake(flake, test_instance)
                    else:
                        flake, rollup = create_flake(test_instance, repo_id)

                        new_flakes[test_instance.test_id] = flake

                        if rollup:
                            rollups_to_update.append(rollup)

            if rollups_to_update:
                DailyTestRollup.objects.bulk_update(
                    rollups_to_update,
                    ["flaky_fail_count"],
                )

            merge_flake_dict = {}

            if new_flakes:
                flakes_to_merge = Flake.objects.bulk_create(new_flakes.values())
                merge_flake_dict: dict[str, Flake] = {
                    flake.test_id: flake for flake in flakes_to_merge
                }

            Flake.objects.bulk_update(
                curr_flakes.values(),
                [
                    "count",
                    "fail_count",
                    "recent_passes_count",
                    "end_date",
                ],
            )

            curr_flakes = {**merge_flake_dict, **curr_flakes}

            new_flakes.clear()

            upload.state = "flake_processed"
            upload.save()
            django_transaction.commit()

        log.info(
            "Successfully processed flakes",
            extra=dict(repoid=repo_id, commit=commit_id),
        )

        return {"successful": True}


def get_test_instances(
    upload: ReportSession,
    flaky_tests: list[str],
) -> list[TestInstance]:
    # get test instances on this upload that either:
    # - failed
    # - passed but belong to an already flaky test

    upload_filter = Q(upload_id=upload.id)
    test_failed_filter = Q(outcome=TestInstance.Outcome.ERROR.value) | Q(
        outcome=TestInstance.Outcome.FAILURE.value
    )
    test_passed_but_flaky_filter = Q(outcome=TestInstance.Outcome.PASS.value) & Q(
        test_id__in=flaky_tests
    )
    test_instances = list(
        TestInstance.objects.filter(
            upload_filter & (test_failed_filter | test_passed_but_flaky_filter)
        )
        .select_related("test")
        .all()
    )
    return test_instances


def fetch_curr_flakes(repo_id: int) -> dict[str, Flake]:
    flakes = Flake.objects.filter(repository_id=repo_id, end_date__isnull=True).all()
    return {flake.test_id: flake for flake in flakes}


def create_flake(
    test_instance: TestInstance,
    repo_id: int,
) -> tuple[Flake, DailyTestRollup | None]:
    # retroactively mark newly caught flake as flaky failure in its rollup
    rollup = DailyTestRollup.objects.filter(
        repoid=repo_id,
        date=test_instance.created_at.date(),
        branch=test_instance.branch,
        test_id=test_instance.test_id,
    ).first()

    if rollup:
        rollup.flaky_fail_count += 1
    else:
        log.warning(
            "Could not find rollup when trying to update its flaky fail count",
            extra=dict(
                repoid=repo_id,
                testid=test_instance.test_id,
                branch=test_instance.branch,
                date=test_instance.created_at.date(),
            ),
        )

    f = Flake(
        repository_id=repo_id,
        test=test_instance.test,
        reduced_error=None,
        count=1,
        fail_count=1,
        start_date=test_instance.created_at,
        recent_passes_count=0,
    )

    return f, rollup


def update_flake(
    flake: Flake,
    test_instance: TestInstance,
) -> None:
    flake.count += 1

    match test_instance.outcome:
        case TestInstance.Outcome.PASS.value:
            flake.recent_passes_count += 1
            if flake.recent_passes_count == FLAKE_EXPIRY_COUNT:
                flake.end_date = test_instance.created_at
        case TestInstance.Outcome.FAILURE.value | TestInstance.Outcome.ERROR.value:
            flake.fail_count += 1
            flake.recent_passes_count = 0
        case _:
            pass


RegisteredProcessFlakesTask = celery_app.register_task(ProcessFlakesTask())
process_flakes_task = celery_app.tasks[RegisteredProcessFlakesTask.name]
