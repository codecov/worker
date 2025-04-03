from typing import TypedDict

import pytest
from django.utils import timezone
from shared.django_apps.reports.models import CommitReport, ReportSession
from shared.django_apps.reports.tests.factories import CommitReportFactory
from shared.django_apps.ta_timeseries.models import Testrun
from shared.django_apps.test_analytics.models import Flake
from shared.helpers.redis import get_redis_connection

from services.test_analytics.ta_process_flakes import KEY_NAME, process_flakes_for_repo


class TestrunData(TypedDict):
    test_id: str
    outcome: str


class UploadData(TypedDict):
    state: str
    testruns: list[TestrunData]


class FlakeDataRequired(TypedDict):
    test_id: str


class FlakeDataOptional(FlakeDataRequired, total=False):
    count: int
    fail_count: int
    recent_passes_count: int
    start_date: timezone.datetime
    end_date: timezone.datetime | None


class SetupResult(TypedDict):
    repoid: int
    commitid: str


pytestmark = pytest.mark.django_db(
    databases=["default", "ta_timeseries"], transaction=True
)


@pytest.fixture
def setup_test_data(db):
    def _create_test_data(
        uploads: list[UploadData],
        existing_flakes: list[FlakeDataOptional],
    ) -> SetupResult:
        report = CommitReportFactory(
            report_type=CommitReport.ReportType.TEST_RESULTS.value,
        )
        report.save()
        repo_id = report.commit.repository.repoid
        commit_id = report.commit.commitid

        redis = get_redis_connection()
        redis.lpush(KEY_NAME.format(repo_id), commit_id)

        sessions = []
        testruns = []
        for upload in uploads:
            session = ReportSession.objects.create(
                report=report,
                state=upload["state"],
            )
            sessions.append(session)

            for testrun_data in upload.get("testruns", []):
                testrun = Testrun.objects.create(
                    timestamp=timezone.now(),
                    test_id=testrun_data["test_id"].encode(),
                    outcome=testrun_data["outcome"],
                    repo_id=repo_id,
                    commit_sha=commit_id,
                    upload_id=session.id,
                )
                testruns.append(testrun)

        created_flakes = []
        for flake_data in existing_flakes:
            flake = Flake.objects.create(
                repoid=repo_id,
                test_id=flake_data["test_id"].encode(),
                recent_passes_count=flake_data.get("recent_passes_count", 0),
                count=flake_data.get("count", 0),
                fail_count=flake_data.get("fail_count", 0),
                start_date=flake_data.get("start_date", timezone.now()),
                end_date=flake_data.get("end_date", None),
            )
            created_flakes.append(flake)

        return {
            "repoid": repo_id,
            "commitid": commit_id,
        }

    return _create_test_data


def test_process_flakes_valid_states_only(setup_test_data):
    result = setup_test_data(
        uploads=[
            {
                "state": "processed",
                "testruns": [{"test_id": "test1", "outcome": "failure"}],
            },
            {
                "state": "finished",
                "testruns": [{"test_id": "test3", "outcome": "failure"}],
            },
            {
                "state": "started",
                "testruns": [{"test_id": "test4", "outcome": "failure"}],
            },
        ],
        existing_flakes=[],
    )

    process_flakes_for_repo(result["repoid"])

    assert Flake.objects.count() == 1


def test_testrun_filters(setup_test_data, snapshot):
    result = setup_test_data(
        uploads=[
            {
                "state": "processed",
                "testruns": [
                    {"test_id": "test1", "outcome": "pass"},
                    {"test_id": "test2", "outcome": "pass"},
                    {"test_id": "test3", "outcome": "failure"},
                    {"test_id": "test4", "outcome": "flaky_failure"},
                    {"test_id": "test5", "outcome": "error"},
                    {"test_id": "test6", "outcome": "skip"},
                ],
            }
        ],
        existing_flakes=[
            {"test_id": "test1", "count": 5, "fail_count": 2},
        ],
    )

    process_flakes_for_repo(result["repoid"])

    flakes = {
        bytes(flake.test_id).decode(): {
            "count": flake.count,
            "fail_count": flake.fail_count,
            "recent_passes_count": flake.recent_passes_count,
        }
        for flake in Flake.objects.all()
    }

    assert snapshot("json") == flakes


def test_update_existing_flakes(setup_test_data):
    result = setup_test_data(
        uploads=[
            {
                "state": "processed",
                "testruns": [
                    {"test_id": "test1", "outcome": "pass"},
                    {"test_id": "test1", "outcome": "failure"},
                ],
            }
        ],
        existing_flakes=[
            {
                "test_id": "test1",
                "count": 5,
                "fail_count": 2,
                "recent_passes_count": 0,
            },
        ],
    )

    process_flakes_for_repo(result["repoid"])

    flake = Flake.objects.get(test_id=b"test1")
    assert flake.count == 7
    assert flake.fail_count == 3
    assert flake.recent_passes_count == 0


def test_create_new_flakes(setup_test_data):
    result = setup_test_data(
        uploads=[
            {
                "state": "processed",
                "testruns": [
                    {"test_id": "test1", "outcome": "failure"},
                    {"test_id": "test2", "outcome": "flaky_failure"},
                    {"test_id": "test3", "outcome": "error"},
                ],
            }
        ],
        existing_flakes=[],
    )

    process_flakes_for_repo(result["repoid"])

    assert Flake.objects.count() == 3
    for test_id in [b"test1", b"test2", b"test3"]:
        flake = Flake.objects.get(test_id=test_id)
        assert flake.count == 1
        assert flake.fail_count == 1
        assert flake.recent_passes_count == 0
        assert flake.start_date is not None
        assert flake.end_date is None


def test_flake_expiry_and_recreation(setup_test_data):
    result = setup_test_data(
        uploads=[
            {
                "state": "processed",
                "testruns": [
                    {"test_id": "test1", "outcome": "pass"},
                    {"test_id": "test1", "outcome": "failure"},
                ],
            }
        ],
        existing_flakes=[
            {
                "test_id": "test1",
                "count": 29,
                "fail_count": 1,
                "recent_passes_count": 29,
            },
        ],
    )

    process_flakes_for_repo(result["repoid"])

    flakes = Flake.objects.filter(test_id=b"test1").order_by("start_date")
    assert len(flakes) == 2

    expired_flake = flakes[0]
    assert expired_flake.end_date is not None
    assert expired_flake.recent_passes_count == 30

    new_flake = flakes[1]
    assert new_flake.end_date is None
    assert new_flake.count == 1
    assert new_flake.fail_count == 1
    assert new_flake.recent_passes_count == 0


def test_flake_expiry_and_more_passes(setup_test_data):
    result = setup_test_data(
        uploads=[
            {
                "state": "processed",
                "testruns": [
                    {"test_id": "test1", "outcome": "pass"},
                    {"test_id": "test1", "outcome": "pass"},
                    {"test_id": "test1", "outcome": "pass"},
                ],
            }
        ],
        existing_flakes=[
            {
                "test_id": "test1",
                "count": 29,
                "fail_count": 1,
                "recent_passes_count": 29,
            },
        ],
    )

    process_flakes_for_repo(result["repoid"])

    flakes = Flake.objects.filter(test_id=b"test1").order_by("start_date")
    assert len(flakes) == 1

    expired_flake = flakes[0]
    assert expired_flake.end_date is not None
    assert expired_flake.recent_passes_count == 30


def test_testrun_outcome_updates(setup_test_data):
    result = setup_test_data(
        uploads=[
            {
                "state": "processed",
                "testruns": [
                    {"test_id": "test1", "outcome": "failure"},
                    {"test_id": "test2", "outcome": "error"},
                    {"test_id": "test3", "outcome": "flaky_failure"},
                ],
            }
        ],
        existing_flakes=[],
    )

    process_flakes_for_repo(result["repoid"])

    testruns = {
        bytes(testrun.test_id).decode(): testrun.outcome
        for testrun in Testrun.objects.all()
    }

    assert testruns == {
        "test1": "flaky_failure",  # Updated from failure
        "test2": "flaky_failure",  # Updated from error
        "test3": "flaky_failure",  # Already flaky_failure, unchanged
    }
