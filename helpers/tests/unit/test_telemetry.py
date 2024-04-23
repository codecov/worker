import asyncio
import threading
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from shared.django_apps.pg_telemetry.models import SimpleMetric as PgSimpleMetric
from shared.django_apps.ts_telemetry.models import SimpleMetric as TsSimpleMetric

from database.models import Commit
from database.tests.factories.core import CommitFactory, OwnerFactory, RepositoryFactory
from helpers.telemetry import MetricContext, TimeseriesTimer, fire_and_forget


def make_metric_context(dbsession):
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

    return MetricContext(
        commit_sha=commit.commitid,
        repo_id=repo.repoid,
        owner_id=owner.ownerid,
    )


@pytest.mark.asyncio
@pytest.mark.real_metric_context
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


class TestMetricContext:
    @pytest.mark.real_metric_context
    def test_populate_complete(self, dbsession, mocker):
        mc = make_metric_context(dbsession)
        assert mc.repo_id is not None
        assert mc.owner_id is not None
        assert mc.commit_sha is not None
        assert mc.repo_slug is None
        assert mc.owner_slug is None
        assert mc.commit_id is None
        assert mc.commit_slug is None
        assert mc.populated == False

        mocker.patch("helpers.telemetry.get_db_session", return_value=dbsession)
        mc.populate()

        assert mc.repo_slug == "github/codecove2e/example-python"
        assert mc.owner_slug == "github/codecove2e"
        assert (
            mc.commit_slug
            == "github/codecove2e/example-python/c5b67303452bbff57cc1f49984339cde39eb1db5"
        )
        assert mc.commit_id is not None

    @pytest.mark.real_metric_context
    def test_populate_no_repo(self, dbsession, mocker):
        mc = make_metric_context(dbsession)
        mc.repo_id = None

        mocker.patch("helpers.telemetry.get_db_session", return_value=dbsession)
        mc.populate()

        assert mc.repo_slug is None
        assert mc.owner_slug == "github/codecove2e"
        assert mc.commit_slug is None
        assert mc.commit_id is None

    @pytest.mark.django_db(databases={"default", "timeseries"})
    @pytest.mark.real_metric_context
    def test_log_simple_metric(self, dbsession, mocker):
        mc = make_metric_context(dbsession)

        desired_time = datetime.now().replace(tzinfo=timezone.utc)
        mock_datetime = mocker.patch("helpers.telemetry.datetime")
        mock_datetime.now.return_value = desired_time

        mocker.patch("helpers.telemetry.get_db_session", return_value=dbsession)
        mc.log_simple_metric("test", 5.0)

        """
        fetched_pg = PgSimpleMetric.objects.get(timestamp=desired_time)
        assert fetched_pg.name == "test"
        assert fetched_pg.value == 5.0
        assert fetched_pg.timestamp == desired_time
        assert fetched_pg.repo_id == mc.repo_id
        assert fetched_pg.owner_id == mc.owner_id
        assert fetched_pg.commit_id == mc.commit_id

        fetched_ts = TsSimpleMetric.objects.get(timestamp=desired_time)
        assert fetched_ts.name == "test"
        assert fetched_ts.value == 5.0
        assert fetched_ts.timestamp == desired_time
        assert fetched_ts.repo_slug == mc.repo_slug
        assert fetched_ts.owner_slug == mc.owner_slug
        assert fetched_ts.commit_slug == mc.commit_slug
        """

    @pytest.mark.asyncio
    @pytest.mark.real_metric_context
    async def test_attempt_log_simple_metric(self, dbsession, mocker):
        mc = make_metric_context(dbsession)
        mock_fn = mocker.patch.object(mc, "log_simple_metric")
        mc.attempt_log_simple_metric("test", 5.0)

        # Yield control so asyncio will go to the next task (logging the metric)
        await asyncio.sleep(0)

        # When control gets back here, the metric should have been logged
        assert ("test", 5.0) in mock_fn.call_args


class TestTimeseriesTimer:
    @pytest.mark.real_metric_context
    def test_sync(self, dbsession, mocker):
        mc = Mock()
        time1 = datetime.fromisoformat("2023-11-21").replace(tzinfo=timezone.utc)
        time2 = datetime.fromisoformat("2023-11-22").replace(tzinfo=timezone.utc)
        time3 = datetime.fromisoformat("2023-11-23").replace(tzinfo=timezone.utc)

        mock_datetime = mocker.patch("helpers.telemetry.datetime")
        mock_datetime.now.side_effect = [time1, time2, time3]

        with TimeseriesTimer(mc, "test_sync_timer", sync=True):
            pass

        expected_value = 86400  # seconds in a day
        assert ("test_sync_timer", expected_value) in mc.log_simple_metric.call_args

    @pytest.mark.asyncio
    @pytest.mark.real_metric_context
    async def test_async(self, dbsession, mocker):
        mc = Mock()
        time1 = datetime.fromisoformat("2023-11-21").replace(tzinfo=timezone.utc)
        time2 = datetime.fromisoformat("2023-11-22").replace(tzinfo=timezone.utc)
        time3 = datetime.fromisoformat("2023-11-23").replace(tzinfo=timezone.utc)

        mock_datetime = mocker.patch("helpers.telemetry.datetime")
        mock_datetime.now.side_effect = [time1, time2, time3]

        with TimeseriesTimer(mc, "test_sync_timer", sync=False):
            pass

        expected_value = 86400  # seconds in a day
        assert (
            "test_sync_timer",
            expected_value,
        ) in mc.attempt_log_simple_metric.call_args
