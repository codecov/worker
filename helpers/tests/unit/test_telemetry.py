import asyncio
import threading
from datetime import datetime, timezone

import pytest

from database.tests.factories.core import CommitFactory, OwnerFactory, RepositoryFactory
from helpers.log_context import LogContext, set_log_context
from helpers.telemetry import (
    TimeseriesTimer,
    attempt_log_simple_metric,
    fire_and_forget,
    log_simple_metric,
)


def populate_log_context(dbsession):
    owner = OwnerFactory.create(
        service="github",
        username="codecove2e",
        unencrypted_oauth_token="test76zow6xgh7modd88noxr245j2z25t4ustoff",
    )
    dbsession.add(owner)

    repo = RepositoryFactory.create(
        owner=owner,
        yaml={"codecov": {"max_report_age": "1y ago"}},
        name="example-python",
    )
    dbsession.add(repo)

    commit = CommitFactory.create(
        message="",
        commitid="c5b67303452bbff57cc1f49984339cde39eb1db5",
        repository=repo,
    )
    dbsession.add(commit)

    dbsession.commit()
    dbsession.expire(owner)
    dbsession.expire(repo)
    dbsession.expire(commit)

    log_context = LogContext(
        commit_sha=commit.commitid,
        commit_id=commit.id_,
        repo_id=repo.repoid,
        owner_id=owner.ownerid,
    )
    set_log_context(log_context)
    return log_context


@pytest.mark.asyncio
async def test_fire_and_forget():
    """
    @fire_and_forget wraps an async function in a sync function that schedules
    it and immediately returns. This test ct ensuresasserts that:
    - an async function with @fire_and_forget doesn't need to be awaited
    - the fired function does eventually run
    """
    # Concurrency primitives that let one concurrent task block on the progress
    # of another concurrent task
    function_was_fired = threading.Event()
    fired_function_ran = threading.Event()

    # Our asynchronous function that we want to fire and forget
    @fire_and_forget
    async def fn():
        # Wait for the caller to tell us to go
        function_was_fired.wait(timeout=1)
        assert function_was_fired.is_set()

        # Tell the caller that we went
        fired_function_ran.set()

    # Because it was declared with @fire_and_forget, no await is needed
    fn()

    # Tell fn() it may go
    function_was_fired.set()

    # Yield control so asyncio will jump to another task (fn())
    await asyncio.sleep(0)

    # Control has returned to us. Wait for fn() to tell us it ran
    fired_function_ran.wait(timeout=1)
    assert fired_function_ran.is_set()


class TestLoggingMetrics:
    @pytest.mark.django_db(databases={"default"})
    def test_log_simple_metric(self, dbsession, mocker):
        log_context = populate_log_context(dbsession)

        desired_time = datetime.now().replace(tzinfo=timezone.utc)
        mock_datetime = mocker.patch("django.utils.timezone")
        mock_datetime.now.return_value = desired_time

        mock_model_create = mocker.patch(
            "helpers.telemetry.PgSimpleMetric.objects.create"
        )
        log_simple_metric("test", 5.0)

        mock_model_create.assert_called_with(
            name="test",
            value=5.0,
            timestamp=desired_time,
            repo_id=log_context.repo_id,
            owner_id=log_context.owner_id,
            commit_id=log_context.commit_id,
        )

    @pytest.mark.asyncio
    async def test_attempt_log_simple_metric(self, dbsession, mocker):
        mock_fn = mocker.patch("helpers.telemetry.log_simple_metric")
        attempt_log_simple_metric("test", 5.0)

        # Yield control so asyncio will go to the next task (logging the metric)
        await asyncio.sleep(0)

        # When control gets back here, the metric should have been logged
        assert ("test", 5.0) in mock_fn.call_args


class TestTimeseriesTimer:
    def test_sync(self, dbsession, mocker):
        mock_fn = mocker.patch("helpers.telemetry.log_simple_metric")
        time1 = datetime.fromisoformat("2023-11-21").replace(tzinfo=timezone.utc)
        time2 = datetime.fromisoformat("2023-11-22").replace(tzinfo=timezone.utc)
        time3 = datetime.fromisoformat("2023-11-23").replace(tzinfo=timezone.utc)

        mock_datetime = mocker.patch("helpers.telemetry.datetime")
        mock_datetime.now.side_effect = [time1, time2, time3]

        with TimeseriesTimer("test_sync_timer", sync=True):
            pass

        expected_value = 86400  # seconds in a day
        assert ("test_sync_timer", expected_value) in mock_fn.call_args

    @pytest.mark.asyncio
    async def test_async(self, dbsession, mocker):
        mock_fn = mocker.patch("helpers.telemetry.attempt_log_simple_metric")
        time1 = datetime.fromisoformat("2023-11-21").replace(tzinfo=timezone.utc)
        time2 = datetime.fromisoformat("2023-11-22").replace(tzinfo=timezone.utc)
        time3 = datetime.fromisoformat("2023-11-23").replace(tzinfo=timezone.utc)

        mock_datetime = mocker.patch("helpers.telemetry.datetime")
        mock_datetime.now.side_effect = [time1, time2, time3]

        with TimeseriesTimer("test_sync_timer", sync=False):
            pass

        expected_value = 86400  # seconds in a day
        assert (
            "test_sync_timer",
            expected_value,
        ) in mock_fn.call_args
