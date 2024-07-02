import datetime as dt
import logging
from typing import Any

from shared.celery_config import process_flakes_task_name
from shared.django_apps.reports.models import Flake, TestInstance

from app import celery_app
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


FlakeDict = dict[Any, Flake]


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

        flake_dict = generate_flake_dict(repo_id)

        for commit_id in commit_id_list:
            test_instances = get_test_instances(commit_id, repo_id, branch)
            for test_instance in test_instances:
                if test_instance.outcome == TestInstance.Outcome.PASS.value:
                    flake = flake_dict.get(test_instance.test_id)
                    if flake is not None:
                        update_passed_flakes(flake)
                elif (
                    test_instance.outcome == TestInstance.Outcome.FAILURE.value
                    or test_instance.outcome == TestInstance.Outcome.ERROR.value
                ):
                    flake = flake_dict.get(test_instance.test_id)
                    upserted_flake = upsert_failed_flake(test_instance, repo_id, flake)
                    if flake is None:
                        flake_dict[upserted_flake.test_id] = upserted_flake

        return {"successful": True}


def get_test_instances(commit_id, repo_id, branch):
    test_instances = TestInstance.objects.filter(
        commitid=commit_id, repoid=repo_id, branch=branch
    ).all()
    return test_instances


def generate_flake_dict(repo_id) -> FlakeDict:
    flakes = Flake.objects.filter(repository_id=repo_id, end_date__isnull=True).all()
    flake_dict = dict()
    for flake in flakes:
        flake_dict[flake.test_id] = flake
    return flake_dict


def update_passed_flakes(flake: Flake):
    flake.count += 1
    flake.recent_passes_count += 1
    if flake.recent_passes_count == 30:
        flake.end_date = dt.datetime.now(tz=dt.UTC)
    flake.save()


def upsert_failed_flake(test_instance: TestInstance, repo_id, flake: Flake | None):
    if flake is None:
        flake = Flake(
            repository_id=repo_id,
            test=test_instance.test,
            reduced_error=None,
            count=1,
            fail_count=1,
            start_date=dt.datetime.now(dt.UTC),
            recent_passes_count=0,
        )
        flake.save()
    else:
        flake.count += 1
        flake.fail_count += 1
        flake.recent_passes_count = 0
        flake.save()

    return flake


RegisteredProcessFlakesTask = celery_app.register_task(ProcessFlakesTask())
process_flakes_task = celery_app.tasks[RegisteredProcessFlakesTask.name]
