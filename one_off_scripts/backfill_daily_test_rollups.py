import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import transaction as django_transaction
from shared.django_apps.core.models import Repository
from shared.django_apps.reports.models import DailyTestRollup, Flake, TestInstance
from test_results_parser import Outcome

logging.basicConfig(level=logging.INFO)
log = logging.getLogger()


@dataclass
class RollupObj:
    pass_count: int
    fail_count: int
    skip_count: int
    flaky_fail_count: int

    sum_duration_seconds: float
    last_duration_seconds: float

    latest_run: datetime

    commits_where_fail: set[str] = field(default_factory=set)


def get_test_analytics_repos(start_repoid):
    # get all repos that have test_analytics_enabled == True
    test_analytics_repos = Repository.objects.filter(
        test_analytics_enabled=True
    ).order_by("repoid")

    if start_repoid is not None:
        test_analytics_repos = test_analytics_repos.filter(repoid__gt=start_repoid)

    return test_analytics_repos


def process_instance(
    rollup_dict: dict[tuple[str, str], RollupObj],
    flake_dict: dict[str, list[tuple[datetime, datetime | None]]],
    instance: TestInstance,
):
    pass_count = 0
    fail_count = 0
    skip_count = 0
    flaky_fail_count = 0
    duration_seconds = 0
    created_at = instance.created_at
    commitid = instance.commitid

    match instance.outcome:
        case Outcome.Pass:
            pass_count = 1
        case Outcome.Skip:
            skip_count = 1
        case _:
            fail_count = 1
            if (flaky_range_list := flake_dict.get(instance.test_id)) is not None:
                for range in flaky_range_list:
                    if range[0] <= instance.created_at and (
                        range[1] is None or instance.created_at < range[1]
                    ):
                        flaky_fail_count += 1
                        break

    if (entry := rollup_dict.get((instance.test_id, instance.branch))) is not None:
        entry.pass_count += pass_count
        entry.fail_count += fail_count
        entry.skip_count += skip_count
        entry.flaky_fail_count += flaky_fail_count
        entry.sum_duration_seconds += duration_seconds
        entry.last_duration_seconds = duration_seconds
        entry.latest_run = created_at
        entry.commits_where_fail.add(commitid)

    else:
        rollup_dict[(instance.test_id, instance.branch)] = RollupObj(
            pass_count,
            fail_count,
            skip_count,
            flaky_fail_count,
            duration_seconds,
            duration_seconds,
            created_at,
            {commitid},
        )


def save_rollups(rollup_dict, repoid, date):
    for obj_key, obj in rollup_dict.items():
        rollup = DailyTestRollup(
            repoid=repoid,
            date=date,
            test_id=obj_key[0],
            branch=obj_key[1],
            pass_count=obj.pass_count,
            fail_count=obj.fail_count,
            skip_count=obj.skip_count,
            flaky_fail_count=obj.flaky_fail_count,
            commits_where_fail=list(obj.commits_where_fail),
            latest_run=obj.latest_run,
            last_duration_seconds=obj.last_duration_seconds,
            avg_duration_seconds=obj.sum_duration_seconds
            / (obj.pass_count + obj.fail_count),
        )

        rollup.save()


def run_impl(
    start_repoid: int | None = None,
    start_date: str | None = None,  # default is 2024-07-16
    end_date: str | None = None,  # default is 2024-09-17
) -> dict[str, bool]:
    log.info(
        f"Updating test instances {start_repoid} {start_date} {end_date}",
        extra=dict(start_repoid=start_repoid, start_date=start_date, end_date=end_date),
    )
    test_analytics_repos = get_test_analytics_repos(start_repoid)

    chunk_size = 10000

    log.info(
        f"Starting backfill for repos {[repo.repoid for repo in test_analytics_repos]}",
        extra=dict(repos=[repo.repoid for repo in test_analytics_repos]),
    )

    for repo in test_analytics_repos:
        repoid = repo.repoid
        log.info(f"Starting backfill for repo {repoid}", extra=dict(repoid=repoid))
        curr_date = date.fromisoformat(start_date) if start_date else date(2024, 7, 16)

        # delete all existing rollups for this day
        DailyTestRollup.objects.filter(repoid=repoid).delete()
        log.info(f"Deleted rollups for repo {repoid}", extra=dict(repoid=repoid))

        until_date = date.fromisoformat(end_date) if end_date else date(2024, 9, 17)

        # get flakes

        flake_list = list(Flake.objects.filter(repository_id=repoid))

        flake_dict: dict[str, list[tuple[datetime, datetime | None]]] = defaultdict(
            list
        )
        for flake in flake_list:
            flake_dict[flake.test_id].append((flake.start_date, flake.end_date))

        while curr_date <= until_date:
            log.info(
                f"Starting backfill for repo on date {repoid} {curr_date}",
                extra=dict(repoid=repoid, date=curr_date),
            )
            rollup_dict: dict[tuple[str, str], RollupObj] = {}

            test_instances = TestInstance.objects.filter(
                repoid=repoid, created_at__date=curr_date
            ).order_by("created_at")

            num_test_instances = test_instances.count()
            if num_test_instances == 0:
                curr_date += timedelta(days=1)
                continue

            chunks = [
                test_instances[i : i + chunk_size]
                for i in range(0, num_test_instances, chunk_size)
            ]

            for chunk in chunks:
                for instance in chunk:
                    if instance.branch is None or instance.commitid is None:
                        continue

                    process_instance(rollup_dict, flake_dict, instance)

            save_rollups(rollup_dict, repoid, curr_date)
            django_transaction.commit()
            log.info(
                f"Committed repo for day {repoid} {curr_date}",
                extra=dict(repoid=repoid, date=curr_date),
            )
            curr_date += timedelta(days=1)

        log.info(f"Finished backfill for repo {repoid}", extra=dict(repoid=repoid))

    return {"successful": True}
