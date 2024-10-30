import pytest

from database.enums import Decoration, Notification, NotificationState
from database.models.core import GithubAppInstallation
from database.tests.factories import (
    CommitFactory,
    CommitNotificationFactory,
    PullFactory,
    RepositoryFactory,
)
from services.comparison.types import Comparison, FullCommit
from services.notification.commit_notifications import (
    create_or_update_commit_notification_from_notification_result,
)
from services.notification.notifiers.base import NotificationResult
from services.notification.notifiers.comment import CommentNotifier
from services.repository import EnrichedPull


@pytest.fixture
def comparison(dbsession):
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
    return Comparison(
        head=FullCommit(commit=head_commit, report=None),
        project_coverage_base=FullCommit(commit=base_commit, report=None),
        patch_coverage_base_commitid=base_commit.commitid,
        enriched_pull=EnrichedPull(database_pull=pull, provider_pull=None),
    )


class TestCommitNotificationsServiceTestCase(object):
    def test_create_or_update_commit_notification_not_yet_exists(
        self, dbsession, comparison
    ):
        pull = comparison.pull
        commit = pull.get_head_commit()
        notifier = CommentNotifier(
            repository=pull.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
            decoration_type=Decoration.standard,
        )
        notify_res = NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation=None,
            data_received=dict(id=123),
            data_sent=dict(a=1, b=2),
        )

        res = create_or_update_commit_notification_from_notification_result(
            comparison, notifier, notify_res
        )
        dbsession.flush()
        assert res.commit_id == commit.id_
        assert res.decoration_type == notifier.decoration_type
        assert res.notification_type == notifier.notification_type
        assert res.state == NotificationState.error

    def test_create_or_update_commit_notification_not_yet_exists_no_pull_but_ghapp_info(
        self, dbsession, comparison
    ):
        comparison.enriched_pull = None
        commit = comparison.head.commit
        app = GithubAppInstallation(owner=commit.repository.owner)
        dbsession.add(app)
        dbsession.flush()
        notifier = CommentNotifier(
            repository=commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
            decoration_type=Decoration.standard,
        )
        notify_res = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_received=dict(id=123),
            data_sent=dict(a=1, b=2),
            github_app_used=app.id,
        )

        res = create_or_update_commit_notification_from_notification_result(
            comparison, notifier, notify_res
        )
        dbsession.flush()
        assert res.commit_id == commit.id_
        assert res.decoration_type == notifier.decoration_type
        assert res.notification_type == notifier.notification_type
        assert res.state == NotificationState.success
        assert res.gh_app_id == app.id

    def test_create_or_update_commit_notification_no_result(
        self, dbsession, comparison
    ):
        commit = comparison.head.commit
        notifier = CommentNotifier(
            repository=commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
            decoration_type=Decoration.standard,
        )
        result_dict = None
        res = create_or_update_commit_notification_from_notification_result(
            comparison, notifier, result_dict
        )
        dbsession.flush()
        assert res.commit_id == commit.id_
        assert res.decoration_type == notifier.decoration_type
        assert res.notification_type == notifier.notification_type
        assert res.state == NotificationState.error

    def test_create_or_update_commit_notification_decoration_change(
        self, dbsession, comparison
    ):
        head_commit = comparison.head.commit

        cn = CommitNotificationFactory(
            commit=head_commit,
            notification_type=Notification.comment,
            decoration_type=Decoration.upgrade,
            state=NotificationState.success,
        )
        dbsession.add(cn)
        dbsession.flush()

        notifier = CommentNotifier(
            repository=head_commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
            decoration_type=Decoration.standard,
        )
        notify_res = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_received=dict(id=123),
            data_sent=dict(a=1, b=2),
        )
        res = create_or_update_commit_notification_from_notification_result(
            comparison, notifier, notify_res
        )
        dbsession.flush()
        assert cn.commit_id == head_commit.id_
        assert cn.decoration_type == notifier.decoration_type
        assert cn.notification_type == notifier.notification_type
        assert cn.state == NotificationState.success

    def test_create_or_update_commit_notification_now_successful(
        self, dbsession, comparison
    ):
        head_commit = comparison.head.commit

        cn = CommitNotificationFactory(
            commit=head_commit,
            notification_type=Notification.comment,
            decoration_type=Decoration.upgrade,
            state=NotificationState.error,
        )
        dbsession.add(cn)
        dbsession.flush()

        notifier = CommentNotifier(
            repository=head_commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
            decoration_type=Decoration.standard,
        )
        notify_res = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_received=dict(id=123),
            data_sent=dict(a=1, b=2),
        )
        res = create_or_update_commit_notification_from_notification_result(
            comparison, notifier, notify_res
        )
        dbsession.flush()
        assert cn.commit_id == head_commit.id_
        assert cn.decoration_type == notifier.decoration_type
        assert cn.notification_type == notifier.notification_type
        assert cn.state == NotificationState.success
