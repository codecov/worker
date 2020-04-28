import dataclasses
import pytest

from database.enums import Decoration, Notification
from database.tests.factories import (
    CommitFactory,
    PullFactory,
    PullNotificationFactory,
    RepositoryFactory,
)
from services.notification.notifiers.comment import CommentNotifier
from services.notification.notifiers.base import NotificationResult
from services.pull_notifications import (
    create_or_update_pull_notification_from_notification_result,
)


@pytest.fixture
def pull(dbsession):
    repository = RepositoryFactory.create(
        owner__username="codecov",
        owner__unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        owner__plan="users-pr-inappm",
        name="example-python",
        image_token="abcdefghij",
        private=True,
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository)
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        state="merged",
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    return pull


class TestPUllNotificationsServiceTestCase(object):
    def test_create_or_update_pull_notification_not_yet_exists(self, dbsession, pull):
        notifier = CommentNotifier(
            repository=pull.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.standard,
        )
        notify_res = NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation=None,
            data_received=dict(id=123),
            data_sent=dict(a=1, b=2),
        )
        result_dict = dataclasses.asdict(notify_res)
        res = create_or_update_pull_notification_from_notification_result(
            pull, notifier, result_dict
        )
        dbsession.flush()
        assert res.repoid == pull.repoid
        assert res.pullid == pull.pullid
        assert res.decoration == notifier.decoration_type
        assert res.notification == notifier.notification_type
        assert res.attempted == notify_res.notification_attempted
        assert res.successful == notify_res.notification_successful

    def test_create_or_update_pull_notification_no_result(self, dbsession, pull):
        notifier = CommentNotifier(
            repository=pull.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.standard,
        )
        result_dict = None
        res = create_or_update_pull_notification_from_notification_result(
            pull, notifier, result_dict
        )
        dbsession.flush()
        assert res.repoid == pull.repoid
        assert res.pullid == pull.pullid
        assert res.decoration == notifier.decoration_type
        assert res.notification == notifier.notification_type
        assert res.attempted == True
        assert res.successful == False

    def test_create_or_update_pull_notification_decoration_change(
        self, dbsession, pull
    ):
        pn = PullNotificationFactory(
            pull=pull,
            notification=Notification.comment,
            decoration=Decoration.upgrade,
            attempted=False,
            successful=None,
        )
        dbsession.add(pn)
        dbsession.flush()

        notifier = CommentNotifier(
            repository=pull.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.standard,
        )
        notify_res = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_received=dict(id=123),
            data_sent=dict(a=1, b=2),
        )
        result_dict = dataclasses.asdict(notify_res)
        res = create_or_update_pull_notification_from_notification_result(
            pull, notifier, result_dict
        )
        dbsession.flush()
        assert pn.repoid == pull.repoid
        assert pn.pullid == pull.pullid
        assert pn.decoration == notifier.decoration_type
        assert pn.notification == notifier.notification_type
        assert pn.attempted == notify_res.notification_attempted
        assert pn.successful == notify_res.notification_successful

    def test_create_or_update_pull_notification_now_successful(self, dbsession, pull):
        pn = PullNotificationFactory(
            pull=pull,
            notification=Notification.comment,
            decoration=Decoration.upgrade,
            attempted=True,
            successful=False,
        )
        dbsession.add(pn)
        dbsession.flush()

        notifier = CommentNotifier(
            repository=pull.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.standard,
        )
        notify_res = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_received=dict(id=123),
            data_sent=dict(a=1, b=2),
        )
        result_dict = dataclasses.asdict(notify_res)
        res = create_or_update_pull_notification_from_notification_result(
            pull, notifier, result_dict
        )
        dbsession.flush()
        assert pn.repoid == pull.repoid
        assert pn.pullid == pull.pullid
        assert pn.decoration == notifier.decoration_type
        assert pn.notification == notifier.notification_type
        assert pn.attempted == notify_res.notification_attempted
        assert pn.successful == notify_res.notification_successful
