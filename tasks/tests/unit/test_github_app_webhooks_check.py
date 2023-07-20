from datetime import datetime, timedelta

import pytest
from shared.torngit.exceptions import TorngitUnauthorizedError

from tasks.github_app_webhooks_check import Github, GitHubAppWebhooksCheckTask


@pytest.fixture
def mock_metrics(mocker):
    from collections import defaultdict

    metrics = defaultdict(int)

    def incr(stat, count=1, rate=1):
        metrics[stat] += count

    def decr(stat, count=1, rate=1):
        metrics[stat] -= count

    mock_incr = mocker.patch("shared.metrics.metrics.incr")
    mock_incr.side_effect = incr

    mock_decr = mocker.patch("shared.metrics.metrics.decr")
    mock_decr.side_effect = decr

    yield metrics


@pytest.fixture
def sample_deliveries():
    sample_deliveries = [
        # time filter: passes, because the `delivered_at` is updated below to be recent
        # status filter: fails, because this was a successful delivery
        # event filter: passes, because it's an installation event
        {
            "id": 17324040107,
            "guid": "53c93580-7a6e-11ed-96c9-5e1ce3e5574e",
            "delivered_at": "2022-12-12T22:42:59Z",
            "redelivery": False,
            "duration": 0.37,
            "status": "OK",
            "status_code": 200,
            "event": "installation_repositories",
            "action": "added",
            "installation_id": None,
            "repository_id": None,
            "url": "",
        },
        # time filter: fails, because the `delivered_at` is old and not updated below
        # status filter: fails, because this was a successful delivery
        # event filter: passes, because it's an installation event
        {
            "id": 17324018336,
            "guid": "40d7f830-7a6e-11ed-8b90-0777e88b1858",
            "delivered_at": "2022-12-12T22:42:30Z",
            "redelivery": False,
            "duration": 2.31,
            "status": "OK",
            "status_code": 200,
            "event": "installation_repositories",
            "action": "removed",
            "installation_id": None,
            "repository_id": None,
            "url": "",
        },
        # time filter: passes, because the `delivered_at` is updated below to be recent
        # status filter: passes, because this was a failed delivery
        # event filter: passes, because it's an installation even
        {
            "id": 17323292984,
            "guid": "0498e8e0-7a6c-11ed-8834-c5eb5a4b102a",
            "delivered_at": "2022-12-12T22:26:28Z",
            "redelivery": False,
            "duration": 0.69,
            "status": "Invalid HTTP Response: 400",
            "status_code": 400,
            "event": "installation",
            "action": "created",
            "installation_id": None,
            "repository_id": None,
            "url": "",
        },
        # time filter: fails, because the `delivered_at` is old and not updated below
        # status filter: passes, because this was a failed delivery
        # event filter: passes, because it's an installation even
        {
            "id": 17323228732,
            "guid": "d41fa780-7a6b-11ed-8890-0619085a3f97",
            "delivered_at": "2022-12-12T22:25:07Z",
            "redelivery": False,
            "duration": 0.74,
            "status": "Invalid HTTP Response: 400",
            "status_code": 400,
            "event": "installation",
            "action": "deleted",
            "installation_id": None,
            "repository_id": None,
            "url": "",
        },
        # time filter: passes, because the `delivered_at` is updated below to be recent
        # status filter: passes, because this was a failed delivery
        # event filter: fails, because it isn't an installation event
        {
            "id": 17323228732,
            "guid": "d41fa780-7a6b-11ed-8890-0619085a3f97",
            "delivered_at": "2022-12-12T22:25:07Z",
            "redelivery": False,
            "duration": 0.74,
            "status": "Invalid HTTP Response: 400",
            "status_code": 400,
            "event": "unknown event",
            "action": "deleted",
            "installation_id": None,
            "repository_id": None,
            "url": "",
        },
        # time filter: fails, because the `delivered_at` is old and not updated below
        # status filter: fails, because this was a successful delivery
        # event filter: fails, because it isn't an installation event
        {
            "id": 17323228732,
            "guid": "d41fa780-7a6b-11ed-8890-0619085a3f97",
            "delivered_at": "2022-12-12T22:25:07Z",
            "redelivery": False,
            "duration": 0.74,
            "status": "Invalid HTTP Response: 400",
            "status_code": 200,
            "event": "unknown event",
            "action": "deleted",
            "installation_id": None,
            "repository_id": None,
            "url": "",
        },
    ]
    now = datetime.now()
    few_hours_ago = now - timedelta(hours=6)
    sample_deliveries[0]["delivered_at"] = few_hours_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
    sample_deliveries[2]["delivered_at"] = few_hours_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
    sample_deliveries[4]["delivered_at"] = few_hours_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
    return sample_deliveries


class TestGHAppWebhooksTask(object):
    @pytest.mark.asyncio
    async def test_get_min_seconds_interval_between_executions(self, dbsession):
        assert isinstance(
            GitHubAppWebhooksCheckTask.get_min_seconds_interval_between_executions(),
            int,
        )
        assert (
            GitHubAppWebhooksCheckTask.get_min_seconds_interval_between_executions()
            > 17000
        )

    def test_apply_time_filter(self, sample_deliveries):
        deliveries_to_test_with = sample_deliveries[0:3]
        # Fix time so the test doesn't break eventually
        now = datetime.now()
        few_hours_ago = now - timedelta(hours=6)
        many_hours_ago_in_range = now - timedelta(hours=7, minutes=50)
        many_hours_ago = now - timedelta(days=2)
        deliveries_to_test_with[0]["delivered_at"] = few_hours_ago.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        deliveries_to_test_with[1]["delivered_at"] = many_hours_ago.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        deliveries_to_test_with[2]["delivered_at"] = many_hours_ago_in_range.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        task = GitHubAppWebhooksCheckTask()
        filtered_deliveries = list(task._apply_time_filter(deliveries_to_test_with))
        assert len(filtered_deliveries) == 2
        assert filtered_deliveries == [
            deliveries_to_test_with[0],
            deliveries_to_test_with[2],
        ]

    def test_apply_event_filter(self, sample_deliveries):
        task = GitHubAppWebhooksCheckTask()
        filtered_deliveries = list(task._apply_event_filter(sample_deliveries))
        assert len(filtered_deliveries) == 4
        assert filtered_deliveries == sample_deliveries[:4]

    def test_apply_status_filter(self, sample_deliveries):
        task = GitHubAppWebhooksCheckTask()
        filtered_deliveries = list(task._apply_status_filter(sample_deliveries))
        assert len(filtered_deliveries) == 3
        assert filtered_deliveries == sample_deliveries[2:5]

    def test_apply_filters_to_deliveries(self, sample_deliveries):
        task = GitHubAppWebhooksCheckTask()
        filtered_deliveries = list(task.apply_filters_to_deliveries(sample_deliveries))
        assert len(filtered_deliveries) == 1
        assert filtered_deliveries[0] == sample_deliveries[2]

    @pytest.mark.asyncio
    async def test_request_redeliveries_return_early(self, mocker):
        fake_redelivery = mocker.patch.object(
            Github,
            "request_webhook_redelivery",
            return_value=True,
        )
        task = GitHubAppWebhooksCheckTask()
        assert await task.request_redeliveries(mocker.MagicMock(), []) == 0
        fake_redelivery.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_check_if_enterprise(self, dbsession, mocker):
        mock_is_enterprise = mocker.patch(
            "tasks.github_app_webhooks_check.is_enterprise", return_value=True
        )
        task = GitHubAppWebhooksCheckTask()
        ans = await task.run_cron_task(dbsession)
        assert ans == dict(checked=False, reason="Enterprise env")
        mock_is_enterprise.assert_called()

    @pytest.mark.asyncio
    async def test_return_on_exception(self, dbsession, mocker):
        def throw_exception(*args, **kwargs):
            raise TorngitUnauthorizedError(
                response_data="error error", message="error error"
            )

        fake_list_deliveries = mocker.patch.object(
            Github,
            "list_webhook_deliveries",
            side_effect=throw_exception,
        )
        fake_redelivery = mocker.patch.object(
            Github,
            "request_webhook_redelivery",
            return_value=True,
        )

        fake_get_token = mocker.patch(
            "tasks.github_app_webhooks_check.get_github_integration_token",
            return_value="integration_jwt_token",
        )
        task = GitHubAppWebhooksCheckTask()
        ans = await task.run_cron_task(dbsession)
        assert ans == dict(
            checked=False,
            reason="Failed with exception. Ending task immediately",
            exception=str(
                TorngitUnauthorizedError(
                    response_data="error error", message="error error"
                )
            ),
            redeliveries_requested=0,
            deliveries_processed=0,
            successful_redeliveries=0,
            pages_processed=0,
        )
        fake_list_deliveries.assert_called()
        fake_get_token.assert_called()
        fake_redelivery.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_run(self, dbsession, mocker, sample_deliveries):
        async def side_effect(*args, **kwargs):
            yield sample_deliveries

        fake_list_deliveries = mocker.patch.object(
            Github,
            "list_webhook_deliveries",
            side_effect=side_effect,
        )
        fake_get_token = mocker.patch(
            "tasks.github_app_webhooks_check.get_github_integration_token",
            return_value="integration_jwt_token",
        )
        fake_redelivery = mocker.patch.object(
            Github,
            "request_webhook_redelivery",
            return_value=True,
        )
        task = GitHubAppWebhooksCheckTask()
        ans = await task.run_cron_task(dbsession)
        assert ans == dict(
            checked=True,
            redeliveries_requested=1,
            deliveries_processed=6,
            successful_redeliveries=1,
            pages_processed=1,
        )
        fake_list_deliveries.assert_called()
        fake_get_token.assert_called()
        fake_redelivery.assert_called()

    @pytest.mark.asyncio
    async def test_redelivery_counters(
        self, dbsession, mocker, sample_deliveries, mock_metrics
    ):
        async def side_effect(*args, **kwargs):
            yield sample_deliveries

        fake_list_deliveries = mocker.patch.object(
            Github,
            "list_webhook_deliveries",
            side_effect=side_effect,
        )
        fake_get_token = mocker.patch(
            "tasks.github_app_webhooks_check.get_github_integration_token",
            return_value="integration_jwt_token",
        )
        fake_redelivery = mocker.patch.object(
            Github,
            "request_webhook_redelivery",
            return_value=True,
        )
        task = GitHubAppWebhooksCheckTask()
        _ = await task.run_cron_task(dbsession)

        # There are 3 failed deliveries above, but 1 of them is old and excluded from the query
        assert mock_metrics["webhooks.github.deliveries.failed"] == 2

        # There are 2 failed deliveries that pass the check above, but one isn't for an installation
        # event so we don't ask for a redelivery
        assert mock_metrics["webhooks.github.deliveries.retry_requested"] == 1
