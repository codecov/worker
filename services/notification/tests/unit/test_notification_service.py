import pytest
from asyncio import TimeoutError as AsyncioTimeoutError, CancelledError

import mock
from celery.exceptions import SoftTimeLimitExceeded

from database.enums import Notification, Decoration
from database.models import PullNotification
from database.tests.factories import RepositoryFactory
from services.decoration import Decoration
from services.notification import NotificationService
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
        service = NotificationService(repository, current_yaml)
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
            title="good_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
            notify=mock.AsyncMock(),
        )
        bad_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            title="bad_notifier",
            notification_type=Notification.status_project,
            decoration_type=Decoration.standard,
        )
        disabled_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=False),
            title="disabled_notifier",
            notification_type=Notification.status_patch,
            decoration_type=Decoration.standard,
            notify=mock.AsyncMock(),
        )
        good_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"some": "data"},
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.side_effect = Exception("This is bad")
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[bad_notifier, good_notifier, disabled_notifier],
        )
        notifications_service = NotificationService(commit.repository, current_yaml)
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
    async def test_notify_individual_notifier_timeout(self, mocker, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
<<<<<<< HEAD
        notifier = mocker.MagicMock(
            title="fake_notifier",
            notify=mocker.MagicMock(return_value=Future()),
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        notifier.notify.return_value = Future()
        notifier.notify.return_value.set_exception(AsyncioTimeoutError())
        notifications_service = NotificationService(commit.repository, current_yaml)
        res = await notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        assert res == {
            "notifier": notifier.name,
            "result": None,
            "title": "fake_notifier",
        }

    @pytest.mark.asyncio
    async def test_notify_individual_notifier_timeout_pull_notification_created(
        self, mocker, dbsession, sample_comparison
    ):
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifier = mocker.MagicMock(
            title="fake_notifier",
            notify=mocker.MagicMock(return_value=Future()),
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        notifier.notify.return_value = Future()
        notifier.notify.return_value.set_exception(AsyncioTimeoutError())
        notifications_service = NotificationService(commit.repository, current_yaml)
        res = await notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        assert res == {
            "notifier": notifier.name,
            "result": None,
            "title": "fake_notifier",
        }
        dbsession.flush()
        pull = sample_comparison.enriched_pull.database_pull
        pn = (
            dbsession.query(PullNotification)
            .filter(
                PullNotification.repoid == pull.repoid,
                PullNotification.pullid == pull.pullid,
                PullNotification.notification == notifier.notification_type,
            )
            .first()
        )
        assert pn is not None
        assert pn.decoration == notifier.decoration_type
        assert pn.attempted is True
        assert pn.successful is False

    @pytest.mark.asyncio
    async def test_notify_individual_notifier_pull_notification_created_then_updated(
        self, mocker, dbsession, sample_comparison
    ):
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifier = mocker.MagicMock(
            title="fake_notifier",
            notify=mocker.MagicMock(return_value=Future()),
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        # first attempt not successful
        notifier.notify.return_value = Future()
        notifier.notify.return_value.set_exception(AsyncioTimeoutError())
=======
        notifier = mocker.MagicMock(title="fake_notifier", notify=mock.AsyncMock())
        notifier.notify.side_effect = AsyncioTimeoutError()
>>>>>>> f8b48ad26ef3413d7f1eb7de5344ae1e6a0127b1
        notifications_service = NotificationService(commit.repository, current_yaml)
        res = await notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        assert res == {
            "notifier": notifier.name,
            "result": None,
            "title": "fake_notifier",
        }
        dbsession.flush()
        pull = sample_comparison.enriched_pull.database_pull
        pn = (
            dbsession.query(PullNotification)
            .filter(
                PullNotification.repoid == pull.repoid,
                PullNotification.pullid == pull.pullid,
                PullNotification.notification == notifier.notification_type,
            )
            .first()
        )
        assert pn is not None
        assert pn.decoration == notifier.decoration_type
        assert pn.attempted is True
        assert pn.successful is False

        # second attempt successful
        notifier.notify.return_value = Future()
        notifier.notify.return_value.set_result(
            NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation="",
                data_sent={"some": "data"},
            )
        )
        res = await notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        dbsession.flush()
        assert pn.attempted is True
        assert pn.successful is True

    @pytest.mark.asyncio
    async def test_notify_individual_notifier_cancellation(
        self, mocker, sample_comparison
    ):
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifier = mocker.MagicMock(title="fake_notifier", notify=mock.AsyncMock())
        notifier.notify.side_effect = CancelledError()
        notifications_service = NotificationService(commit.repository, current_yaml)
        with pytest.raises(CancelledError):
            await notifications_service.notify_individual_notifier(
                notifier, sample_comparison
            )

    @pytest.mark.asyncio
    async def test_notify_timeout_exception(self, mocker, dbsession, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        good_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mock.AsyncMock(),
            title="good_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        bad_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mock.AsyncMock(),
            title="bad_notifier",
            notification_type=Notification.status_patch,
            decoration_type=Decoration.standard,
        )
        disabled_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=False),
            title="disabled_notifier",
            notification_type=Notification.status_changes,
            decoration_type=Decoration.standard,
        )
        good_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"some": "data"},
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.side_effect = SoftTimeLimitExceeded()
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[bad_notifier, good_notifier, disabled_notifier],
        )
        notifications_service = NotificationService(commit.repository, current_yaml)
        with pytest.raises(SoftTimeLimitExceeded):
            await notifications_service.notify(sample_comparison)

        dbsession.flush()
        pull_notifications = sample_comparison.enriched_pull.database_pull.notifications
        assert len(pull_notifications) == 2
        for pn in pull_notifications:
            assert pn.attempted is True
            assert pn.decoration == Decoration.standard
            assert pn.notification in (Notification.comment, Notification.status_patch)

    @pytest.mark.asyncio
    async def test_not_licensed_enterprise(self, mocker, dbsession, sample_comparison):
        mocker.patch("services.notification.is_properly_licensed", return_value=False)
        mock_notify_individual_notifier = mocker.patch.object(
            NotificationService, "notify_individual_notifier"
        )
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifications_service = NotificationService(commit.repository, current_yaml)
        expected_result = []
        res = await notifications_service.notify(sample_comparison)
        assert expected_result == res
        assert not mock_notify_individual_notifier.called
