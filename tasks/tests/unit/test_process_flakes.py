import datetime as dt
from collections import defaultdict

import pytest
import time_machine
from shared.django_apps.core.models import Commit
from shared.django_apps.core.tests.factories import CommitFactory, RepositoryFactory
from shared.django_apps.reports.models import (
    CommitReport,
    DailyTestRollup,
    Flake,
    TestInstance,
)
from shared.django_apps.reports.tests.factories import (
    DailyTestRollupFactory,
    FlakeFactory,
    TestFactory,
    TestInstanceFactory,
    UploadFactory,
)

from services.processing.flake_processing import (
    create_flake,
    fetch_curr_flakes,
    get_test_instances,
    update_flake,
)
from services.redis import get_redis_connection
from tasks.process_flakes import (
    NEW_KEY,
    OLD_KEY,
    ProcessFlakesTask,
    process_flakes_task,
)
from tests.helpers import mock_all_plans_and_tiers

pytestmark = pytest.mark.django_db


class RepoSimulator:
    def __init__(self):
        self.repo = RepositoryFactory()
        self.repo.save()
        self.test_count = 0
        self.branch_number = 0

        self.redis = get_redis_connection()

        self.test_map = defaultdict(lambda: TestFactory(id=self.test_count))

    def run_task(self, repo_id: int, commit_id: str):
        self.redis.delete(NEW_KEY.format(repo_id))
        self.redis.delete(OLD_KEY.format(repo_id))
        self.redis.rpush(NEW_KEY.format(repo_id), commit_id)
        ProcessFlakesTask().run_impl(None, repo_id=repo_id, commit_id=commit_id)

    def create_commit(self) -> Commit:
        c = CommitFactory(
            repository=self.repo, merged=False, branch=str(self.branch_number)
        )
        c.save()
        self.branch_number += 1
        self.test_count = 0
        return c

    def add_test_instance(
        self,
        c: Commit,
        outcome: str = TestInstance.Outcome.PASS.value,
        state: str = "processed",
    ) -> TestInstance:
        upload = UploadFactory(
            report__commit=c,
            report__report_type=CommitReport.ReportType.TEST_RESULTS.value,
            state=state,
        )
        upload.save()
        ti = TestInstanceFactory(
            commitid=c.commitid,
            repoid=self.repo.repoid,
            branch=c.branch,
            outcome=outcome,
            test=self.test_map[self.test_count],
            upload=upload,
        )
        ti.save()

        rollup, _ = DailyTestRollup.objects.get_or_create(
            repoid=self.repo.repoid,
            date=dt.date.today(),
            test=self.test_map[self.test_count],
            branch=c.branch,
            defaults={
                "pass_count": 0,
                "skip_count": 0,
                "fail_count": 0,
                "flaky_fail_count": 0,
                "avg_duration_seconds": 0.0,
                "last_duration_seconds": 0.0,
                "latest_run": dt.datetime.now(tz=dt.timezone.utc),
                "commits_where_fail": [],
            },
        )

        match outcome:
            case TestInstance.Outcome.PASS.value:
                rollup.pass_count += 1
            case TestInstance.Outcome.SKIP.value:
                rollup.skip_count += 1
            case _:
                rollup.fail_count += 1

                s = set(rollup.commits_where_fail)
                s.add(c.commitid)
                rollup.commits_where_fail = list(s)

                flake = Flake.objects.filter(
                    repository_id=self.repo.repoid,
                    test=self.test_map[self.test_count],
                ).first()

                if flake:
                    rollup.flaky_fail_count += 1

        rollup.save()

        self.test_count += 1

        return ti

    def reset(self):
        self.repo = RepositoryFactory()
        self.repo.save()
        self.test_count = 0


def test_generate_flake_dict(transactional_db):
    repo = RepositoryFactory()

    flake_dict = fetch_curr_flakes(repo.repoid)

    assert len(flake_dict) == 0

    f = FlakeFactory(repository=repo, test__id="id")
    f.save()

    flake_dict = fetch_curr_flakes(repo.repoid)

    assert len(flake_dict) == 1
    assert "id" in flake_dict


def test_get_test_instances_when_test_is_flaky(transactional_db):
    repo = RepositoryFactory()
    commit = CommitFactory()
    upload = UploadFactory(report__commit=commit)

    ti = TestInstanceFactory(
        commitid=commit.commitid,
        repoid=repo.repoid,
        branch="main",
        outcome=TestInstance.Outcome.FAILURE.value,
        upload=upload,
    )
    ti.save()

    tis = get_test_instances(upload, flaky_tests=[ti.test_id])
    assert len(tis) == 1
    assert tis[0].commitid


def test_get_test_instances_when_instance_is_failure(transactional_db):
    repo = RepositoryFactory()
    commit = CommitFactory()
    upload = UploadFactory(report__commit=commit)

    ti = TestInstanceFactory(
        commitid=commit.commitid,
        repoid=repo.repoid,
        branch="main",
        outcome=TestInstance.Outcome.FAILURE.value,
        upload=upload,
    )
    ti.save()

    tis = get_test_instances(upload, flaky_tests=[])
    assert len(tis) == 1
    assert tis[0].commitid


def test_get_test_instances_when_test_is_flaky_and_instance_is_skip(transactional_db):
    repo = RepositoryFactory()
    commit = CommitFactory()
    upload = UploadFactory(report__commit=commit)

    ti = TestInstanceFactory(
        commitid=commit.commitid,
        repoid=repo.repoid,
        branch="main",
        outcome=TestInstance.Outcome.SKIP.value,
        upload=upload,
    )
    ti.save()

    tis = get_test_instances(upload, flaky_tests=[ti.test_id])
    assert len(tis) == 0


def test_get_test_instances_when_instance_is_pass(transactional_db):
    repo = RepositoryFactory()
    commit = CommitFactory()
    upload = UploadFactory(report__commit=commit)

    ti = TestInstanceFactory(
        commitid=commit.commitid,
        repoid=repo.repoid,
        branch="main",
        outcome=TestInstance.Outcome.PASS.value,
        upload=upload,
    )
    ti.save()

    tis = get_test_instances(upload, flaky_tests=[])
    assert len(tis) == 0


def test_update_flake_pass(transactional_db):
    rs = RepoSimulator()
    c = rs.create_commit()
    ti = rs.add_test_instance(c, outcome=TestInstance.Outcome.PASS.value)

    f = FlakeFactory(test=ti.test, repository=rs.repo)
    f.save()
    assert f.count == 0
    assert f.recent_passes_count == 0

    update_flake(f, ti)

    assert f.count == 1
    assert f.recent_passes_count == 1


def test_update_flake_fail(transactional_db):
    rs = RepoSimulator()
    c = rs.create_commit()
    ti = rs.add_test_instance(c, outcome=TestInstance.Outcome.FAILURE.value)

    f = FlakeFactory(test=ti.test, repository=rs.repo)
    f.save()
    assert f.count == 0
    assert f.recent_passes_count == 0

    update_flake(f, ti)

    assert f.count == 1
    assert f.recent_passes_count == 0
    assert f.fail_count == 1


def test_upsert_failed_flakes(transactional_db):
    repo = RepositoryFactory()
    repo.save()
    commit = CommitFactory()
    commit.save()
    ti = TestInstanceFactory(
        commitid=commit.commitid, repoid=repo.repoid, branch="main"
    )
    ti.save()

    rollup = DailyTestRollupFactory(
        repoid=repo.repoid,
        test=ti.test,
        branch="main",
        date=dt.date.today(),
        flaky_fail_count=0,
    )
    rollup.save()

    f, r = create_flake(ti, repo.repoid)
    assert f.count == 1
    assert f.fail_count == 1
    assert f.recent_passes_count == 0
    assert f.test == ti.test

    assert r is not None
    assert r.flaky_fail_count == 1


def test_upsert_failed_flakes_rollup_is_none():
    repo = RepositoryFactory()
    repo.save()
    commit = CommitFactory()
    commit.save()
    ti = TestInstanceFactory(
        commitid=commit.commitid, repoid=repo.repoid, branch="main"
    )
    ti.save()

    f, r = create_flake(ti, repo.repoid)
    assert f.count == 1
    assert f.fail_count == 1
    assert f.recent_passes_count == 0
    assert f.test == ti.test

    assert r is None


def test_it_handles_only_passes(transactional_db):
    rs = RepoSimulator()
    c1 = rs.create_commit()
    rs.add_test_instance(c1)
    rs.add_test_instance(c1)

    rs.run_task(rs.repo.repoid, c1.commitid)

    assert len(Flake.objects.all()) == 0


@time_machine.travel(dt.datetime.now(tz=dt.UTC), tick=False)
def test_it_creates_flakes_from_processed_uploads(transactional_db):
    rs = RepoSimulator()
    c1 = rs.create_commit()
    rs.add_test_instance(c1, state="v2_finished")
    rs.add_test_instance(
        c1, outcome=TestInstance.Outcome.FAILURE.value, state="processed"
    )

    rs.run_task(rs.repo.repoid, c1.commitid)

    assert len(Flake.objects.all()) == 1
    flake = Flake.objects.first()

    assert flake is not None
    assert flake.count == 1
    assert flake.fail_count == 1
    assert flake.start_date == dt.datetime.now(tz=dt.UTC)


@time_machine.travel(dt.datetime.now(tz=dt.UTC), tick=False)
def test_it_does_not_create_flakes_from_flake_processed_uploads():
    rs = RepoSimulator()
    c1 = rs.create_commit()
    rs.add_test_instance(c1, state="v2_processed")
    rs.add_test_instance(
        c1, outcome=TestInstance.Outcome.FAILURE.value, state="flake_processed"
    )

    rs.run_task(rs.repo.repoid, c1.commitid)

    assert len(Flake.objects.all()) == 0


@time_machine.travel(dt.datetime.now(tz=dt.UTC), tick=False)
def test_it_processes_two_commits_separately(transactional_db):
    rs = RepoSimulator()
    c1 = rs.create_commit()
    rs.add_test_instance(c1, outcome=TestInstance.Outcome.FAILURE.value)

    rs.run_task(rs.repo.repoid, c1.commitid)

    c2 = rs.create_commit()
    rs.add_test_instance(c2, outcome=TestInstance.Outcome.FAILURE.value)

    rs.run_task(rs.repo.repoid, c2.commitid)

    assert len(Flake.objects.all()) == 1
    flake = Flake.objects.first()

    assert flake is not None
    assert flake.recent_passes_count == 0
    assert flake.count == 2
    assert flake.fail_count == 2
    assert flake.start_date == dt.datetime.now(dt.UTC)


def test_it_creates_flakes_expires(transactional_db):
    with time_machine.travel(dt.datetime.now(tz=dt.UTC), tick=False) as traveller:
        rs = RepoSimulator()
        commits: list[str] = []
        c1 = rs.create_commit()
        rs.add_test_instance(c1, outcome=TestInstance.Outcome.FAILURE.value)

        rs.run_task(rs.repo.repoid, c1.commitid)

        old_time = dt.datetime.now(dt.UTC)
        traveller.shift(dt.timedelta(seconds=100))
        new_time = dt.datetime.now(dt.UTC)

        for _ in range(0, 29):
            c = rs.create_commit()
            rs.add_test_instance(c, outcome=TestInstance.Outcome.PASS.value)
            commits.append(c.commitid)

            rs.run_task(rs.repo.repoid, c.commitid)

        assert len(Flake.objects.all()) == 1
        flake = Flake.objects.first()

        assert flake is not None
        assert flake.recent_passes_count == 29
        assert flake.count == 30
        assert flake.fail_count == 1
        assert flake.start_date == old_time
        assert flake.end_date is None

        c = rs.create_commit()
        rs.add_test_instance(c, outcome=TestInstance.Outcome.PASS.value)

        rs.run_task(rs.repo.repoid, c.commitid)

        assert len(Flake.objects.all()) == 1
        flake = Flake.objects.first()

        assert flake is not None
        assert flake.recent_passes_count == 30
        assert flake.count == 31
        assert flake.fail_count == 1
        assert flake.start_date == old_time
        assert flake.end_date == new_time


def test_it_creates_rollups(transactional_db):
    with time_machine.travel("1970-1-1T00:00:00Z"):
        rs = RepoSimulator()
        c1 = rs.create_commit()
        rs.add_test_instance(c1, outcome=TestInstance.Outcome.FAILURE.value)
        rs.add_test_instance(c1, outcome=TestInstance.Outcome.FAILURE.value)

        rs.run_task(rs.repo.repoid, c1.commitid)

    with time_machine.travel("1970-1-2T00:00:00Z"):
        c2 = rs.create_commit()
        rs.add_test_instance(c2, outcome=TestInstance.Outcome.FAILURE.value)
        rs.add_test_instance(c2, outcome=TestInstance.Outcome.FAILURE.value)

        rs.run_task(rs.repo.repoid, c2.commitid)

        rollups = DailyTestRollup.objects.all().order_by("date")

        assert len(rollups) == 4

        assert rollups[0].fail_count == 1
        assert rollups[0].flaky_fail_count == 1
        assert rollups[0].date == dt.date.today() - dt.timedelta(days=1)

        assert rollups[1].fail_count == 1
        assert rollups[1].flaky_fail_count == 1
        assert rollups[1].date == dt.date.today() - dt.timedelta(days=1)

        assert rollups[2].fail_count == 1
        assert rollups[2].flaky_fail_count == 1
        assert rollups[2].date == dt.date.today()

        assert rollups[3].fail_count == 1
        assert rollups[3].flaky_fail_count == 1
        assert rollups[3].date == dt.date.today()


def test_it_locks(mocker):
    mock_all_plans_and_tiers()
    result2 = None

    def first_call(repo_id: int, commit_id: str):
        nonlocal result2
        if result2 is None:
            result2 = process_flakes_task.s(
                repo_id=repo_id,
                commit_id=commit_id,
                use_timeseries=False,
            ).apply()
        return None

    mock_process = mocker.patch(
        "tasks.process_flakes.process_flake_for_repo_commit",
        side_effect=first_call,
    )

    redis_client = get_redis_connection()
    repo_id = 1
    commit_ids = ["abc123", "def456", "ghi789"]

    redis_client.delete(OLD_KEY.format(repo_id))
    redis_client.delete(NEW_KEY.format(repo_id))
    for commit_id in commit_ids:
        redis_client.rpush(NEW_KEY.format(repo_id), commit_id)

    result1 = process_flakes_task.s(
        repo_id=repo_id,
        commit_id=commit_ids[0],
        use_timeseries=False,
    ).apply()

    assert result1 is not None
    assert result2 is not None
    assert result1.get() == {"successful": True}
    assert result2.get() == {"successful": False}

    assert mock_process.call_count == len(commit_ids)
    mock_process.assert_has_calls(
        [mocker.call(repo_id, commit_id) for commit_id in commit_ids]
    )
