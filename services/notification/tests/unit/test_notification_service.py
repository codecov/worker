import pytest
from asyncio import Future

from celery.exceptions import SoftTimeLimitExceeded

from services.notification import NotificationService
from database.tests.factories import RepositoryFactory
from services.decoration import Decoration
from services.notification.notifiers.base import NotificationResult
from services.notification.types import Comparison, FullCommit, EnrichedPull
from database.tests.factories import (
    CommitFactory,
    PullFactory,
)


@pytest.fixture
def sample_comparison(dbsession, request):
    repository = RepositoryFactory.create(owner__username=request.node.name,)
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    pull = PullFactory.create(
        repository=repository, base=base_commit.commitid, head=head_commit.commitid
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(commit=base_commit, report=None)
    head_full_commit = FullCommit(commit=head_commit, report=None)
    return Comparison(
        head=head_full_commit,
        base=base_full_commit,
        enriched_pull=EnrichedPull(database_pull=pull, provider_pull={}),
    )


class TestNotificationService(object):
    def test_get_notifiers_instances_only_third_party(
        self, dbsession, mock_configuration
    ):
        mock_configuration.params["services"] = {
            "notifications": {"slack": ["slack.com"]}
        }
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            owner__username="ThiagoCodecov",
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {
            "coverage": {"notify": {"slack": {"default": {"field": "1y ago"}}}}
        }
        service = NotificationService(repository, current_yaml, Decoration.standard)
        instances = list(service.get_notifiers_instances())
        assert len(instances) == 1
        instance = instances[0]
        assert instance.repository == repository
        assert instance.title == "default"
        assert instance.notifier_yaml_settings == {"field": "1y ago"}
        assert instance.site_settings == ["slack.com"]
        assert instance.current_yaml == current_yaml

    @pytest.mark.asyncio
    async def test_notify_general_exception(self, mocker, dbsession, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        good_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mocker.MagicMock(return_value=Future()),
            title="good_notifier",
        )
        bad_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mocker.MagicMock(return_value=Future()),
            title="bad_notifier",
        )
        disabled_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=False), title="disabled_notifier"
        )
        good_notifier.notify.return_value.set_result(
            NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation="",
                data_sent={"some": "data"},
            )
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.return_value.set_exception(Exception("This is bad"))
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[bad_notifier, good_notifier, disabled_notifier],
        )
        notifications_service = NotificationService(commit.repository, current_yaml, Decoration.standard)
        expected_result = [
            {"notifier": "bad_name", "title": "bad_notifier", "result": None},
            {
                "notifier": "good_name",
                "title": "good_notifier",
                "result": {
                    "notification_attempted": True,
                    "notification_successful": True,
                    "explanation": "",
                    "data_sent": {"some": "data"},
                    "data_received": None,
                },
            },
        ]
        res = await notifications_service.notify(sample_comparison)
        assert expected_result == res

    @pytest.mark.asyncio
    async def test_notify_timeout_exception(self, mocker, dbsession, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        good_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mocker.MagicMock(return_value=Future()),
            title="good_notifier",
        )
        bad_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mocker.MagicMock(return_value=Future()),
            title="bad_notifier",
        )
        disabled_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=False), title="disabled_notifier"
        )
        good_notifier.notify.return_value.set_result(
            NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation="",
                data_sent={"some": "data"},
            )
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.return_value.set_exception(SoftTimeLimitExceeded())
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[bad_notifier, good_notifier, disabled_notifier],
        )
        notifications_service = NotificationService(commit.repository, current_yaml, Decoration.standard)
        with pytest.raises(SoftTimeLimitExceeded):
            await notifications_service.notify(sample_comparison)
