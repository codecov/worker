import logging

from django.db.models import Q
from shared.celery_config import process_flakes_task_name
from shared.django_apps.reports.models import DailyTestRollup, Flake, TestInstance

from app import celery_app
from helpers.metrics import metrics
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


FlakeDict = dict[tuple[str, int], Flake]

FLAKE_EXPIRY_COUNT = 30


class ProcessFlakesTask(BaseCodecovTask, name=process_flakes_task_name):
    """
    This task is currently called in the test results finisher task and in the sync pulls task
    """

    def run_impl(
        self,
        _db_session,
        *,
        repo_id,
        commit_id_list,
        branch,
        **kwargs,
    ):
        repo_id = int(repo_id)
        log.info(
            "Received process flakes task",
            extra=dict(repoid=repo_id, commit=commit_id_list),
        )

        with metrics.timer("process_flakes"):
            flake_dict = generate_flake_dict(repo_id)

            flaky_tests: list[str] = [
                test_id for (test_id, _) in list(flake_dict.keys())
            ]

            for commit_id in commit_id_list:
                test_instances = get_test_instances(
                    commit_id, repo_id, branch, flaky_tests
                )
                for test_instance in test_instances:
                    if test_instance.outcome == TestInstance.Outcome.PASS.value:
                        flake = flake_dict.get(
                            (test_instance.test_id, test_instance.reduced_error_id)
                        )
                        if flake is not None:
                            update_passed_flakes(test_instance, flake)
                    elif test_instance.outcome in (
                        TestInstance.Outcome.FAILURE.value,
                        TestInstance.Outcome.ERROR.value,
                    ):
                        flake = flake_dict.get(
                            (test_instance.test_id, test_instance.reduced_error_id)
                        )
                        upserted_flake = upsert_failed_flake(
                            test_instance, flake, repo_id
                        )
                        if flake is None:
                            flake_dict[
                                (
                                    upserted_flake.test_id,
                                    upserted_flake.reduced_error_id,
                                )
                            ] = upserted_flake

        log.info(
            "Successfully processed flakes",
            extra=dict(repoid=repo_id, commit=commit_id_list),
        )

        return {"successful": True}


def get_test_instances(
    commit_id: str,
    repo_id: int,
    branch: str,
    flaky_tests: list[str],
) -> list[TestInstance]:
    # get test instances on this repo commit branch combination that either:
    # - failed
    # - passed but belong to an already flaky test

    repo_commit_branch_filter = (
        Q(commitid=commit_id) & Q(repoid=repo_id) & Q(branch=branch)
    )
    test_failed_filter = Q(outcome=TestInstance.Outcome.ERROR.value) | Q(
        outcome=TestInstance.Outcome.FAILURE.value
    )
    test_passed_but_flaky_filter = Q(outcome=TestInstance.Outcome.PASS.value) & Q(
        test_id__in=flaky_tests
    )
    test_instances = list(
        TestInstance.objects.filter(
            repo_commit_branch_filter
            & (test_failed_filter | test_passed_but_flaky_filter)
        ).all()
    )
    return test_instances


def generate_flake_dict(repo_id: int) -> FlakeDict:
    flakes = Flake.objects.filter(repository_id=repo_id, end_date__isnull=True).all()
    flake_dict = dict()
    for flake in flakes:
        flake_dict[(flake.test_id, flake.reduced_error_id)] = flake
    return flake_dict


def update_passed_flakes(test_instance: TestInstance, flake: Flake) -> None:
    flake.count += 1
    flake.recent_passes_count += 1

    if flake.recent_passes_count == FLAKE_EXPIRY_COUNT:
        flake.end_date = test_instance.created_at

    flake.save()


def upsert_failed_flake(
    test_instance: TestInstance,
    flake: Flake | None,
    repo_id: int,
) -> Flake:
    if flake is None:
        flake = Flake(
            repository_id=repo_id,
            test=test_instance.test,
            reduced_error=test_instance.reduced_error_id,
            count=1,
            fail_count=1,
            start_date=test_instance.created_at,
            recent_passes_count=0,
        )
        flake.save()

        # retroactively mark newly caught flake as flaky failure in its rollup
        rollup = DailyTestRollup.objects.filter(
            repoid=repo_id,
            date=test_instance.created_at.date(),
            branch=test_instance.branch,
            test_id=test_instance.test_id,
        ).first()

        if rollup:
            rollup.flaky_fail_count += 1
            rollup.save()
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
    else:
        flake.count += 1
        flake.fail_count += 1
        flake.recent_passes_count = 0
        flake.save()

    return flake


RegisteredProcessFlakesTask = celery_app.register_task(ProcessFlakesTask())
process_flakes_task = celery_app.tasks[RegisteredProcessFlakesTask.name]
