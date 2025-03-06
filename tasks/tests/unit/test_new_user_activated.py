from datetime import datetime

import pytest

from database.enums import Decoration, Notification, NotificationState
from database.tests.factories import (
    CommitFactory,
    CommitNotificationFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from tasks.new_user_activated import NewUserActivatedTask
from tests.helpers import mock_all_plans_and_tiers


@pytest.fixture
def pull(dbsession):
    repository = RepositoryFactory.create(
        owner__username="codecov-test",
        owner__unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3bb",
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
        updatestamp=datetime.now(),
        state="open",
        author__username="tjbiii",
        author__unencrypted_oauth_token="testmlqkug1uo08z1ic8kq4gkivba2owf538c7mz",
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    return pull


class TestNewUserActivatedTaskUnit(object):
    @pytest.fixture(autouse=True)
    def mock_all_plans_and_tiers(self):
        mock_all_plans_and_tiers()

    @pytest.mark.django_db
    def test_get_pulls_authored_by_user_none(self, dbsession, pull):
        org_ownerid = pull.repository.ownerid
        user_ownerid_with_no_pulls = 12312412
        res = NewUserActivatedTask().get_pulls_authored_by_user(
            dbsession, org_ownerid, user_ownerid_with_no_pulls
        )
        assert res == []

    @pytest.mark.django_db
    def test_get_pulls_authored_by_user(self, dbsession, pull):
        pull_by_other_author = PullFactory.create(
            repository=pull.repository,
            updatestamp=datetime.now(),
            state="open",
            author__username="1nf1nt3l00p",
            author__unencrypted_oauth_token="testolcdo9icfq7lgpumzd2xq3aln6z4kxe6",
        )
        dbsession.add(pull_by_other_author)
        dbsession.flush()
        org_ownerid = pull.repository.ownerid
        user_ownerid = pull.author.ownerid
        res = NewUserActivatedTask().get_pulls_authored_by_user(
            dbsession, org_ownerid, user_ownerid
        )
        assert len(res) == 1
        authored_pull = res[0]
        assert authored_pull.state == "open"
        assert authored_pull.author.ownerid == user_ownerid

    @pytest.mark.django_db
    def test_is_org_on_pr_plan_gitlab_subgroup(self, dbsession, with_sql_functions):
        root_group = OwnerFactory.create(
            username="root_group",
            service="gitlab",
            unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
            plan="users-pr-inappm",
            plan_activated_users=[],
        )
        subgroup = OwnerFactory.create(
            username="subgroup",
            service="gitlab",
            unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
            plan=None,
            parent_service_id=root_group.service_id,
        )
        dbsession.add(subgroup)
        dbsession.add(root_group)
        dbsession.flush()

        res = NewUserActivatedTask().is_org_on_pr_plan(dbsession, subgroup.ownerid)
        assert res is True

    @pytest.mark.django_db
    def test_org_not_found(self, mocker, dbsession):
        unknown_org_ownerid = 404123
        user_ownerid = 123
        res = NewUserActivatedTask().run_impl(
            dbsession, unknown_org_ownerid, user_ownerid
        )
        assert res == {
            "notifies_scheduled": False,
            "pulls_notified": [],
            "reason": "org not on pr author billing plan",
        }

    @pytest.mark.django_db
    def test_org_not_on_pr_plan(self, mocker, dbsession, pull):
        pull.repository.owner.plan = "users-inappm"
        dbsession.flush()
        res = NewUserActivatedTask().run_impl(
            dbsession, pull.repository.owner.ownerid, pull.author.ownerid
        )
        assert res == {
            "notifies_scheduled": False,
            "pulls_notified": [],
            "reason": "org not on pr author billing plan",
        }

    @pytest.mark.django_db
    def test_no_commit_notifications_found(self, mocker, dbsession, pull):
        mocked_possibly_resend_notifications = mocker.patch(
            "tasks.new_user_activated.NewUserActivatedTask.possibly_resend_notifications"
        )
        res = NewUserActivatedTask().run_impl(
            dbsession, pull.repository.owner.ownerid, pull.author.ownerid
        )
        assert res == {
            "notifies_scheduled": False,
            "pulls_notified": [],
            "reason": "no pulls/pull notifications met criteria",
        }
        assert not mocked_possibly_resend_notifications.called

    @pytest.mark.django_db
    def test_no_head_commit_on_pull(self, mocker, dbsession, pull):
        pull.head = None
        mocked_possibly_resend_notifications = mocker.patch(
            "tasks.new_user_activated.NewUserActivatedTask.possibly_resend_notifications"
        )
        res = NewUserActivatedTask().run_impl(
            dbsession, pull.repository.owner.ownerid, pull.author.ownerid
        )
        assert res == {
            "notifies_scheduled": False,
            "pulls_notified": [],
            "reason": "no pulls/pull notifications met criteria",
        }
        assert not mocked_possibly_resend_notifications.called

    @pytest.mark.django_db
    def test_commit_notifications_all_standard(self, mocker, dbsession, pull):
        pull_head_commit = pull.get_head_commit()
        cn1 = CommitNotificationFactory.create(
            commit=pull_head_commit,
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
            state=NotificationState.pending,
        )
        cn2 = CommitNotificationFactory.create(
            commit=pull_head_commit,
            notification_type=Notification.status_changes,
            decoration_type=Decoration.standard,
            state=NotificationState.pending,
        )
        dbsession.add(cn1)
        dbsession.add(cn2)
        dbsession.flush()

        res = NewUserActivatedTask().run_impl(
            dbsession, pull.repository.owner.ownerid, pull.author.ownerid
        )
        assert res == {
            "notifies_scheduled": False,
            "pulls_notified": [],
            "reason": "no pulls/pull notifications met criteria",
        }

    @pytest.mark.django_db
    def test_commit_notifications_resend_single_pull(self, mocker, dbsession, pull):
        pull_head_commit = pull.get_head_commit()
        cn1 = CommitNotificationFactory.create(
            commit=pull_head_commit,
            notification_type=Notification.comment,
            decoration_type=Decoration.upgrade,
            state=NotificationState.pending,
        )
        cn2 = CommitNotificationFactory.create(
            commit=pull_head_commit,
            notification_type=Notification.status_changes,
            decoration_type=Decoration.upgrade,
            state=NotificationState.pending,
        )
        dbsession.add(cn1)
        dbsession.add(cn2)
        dbsession.flush()

        mocked_app = mocker.patch.object(
            NewUserActivatedTask,
            "app",
            tasks={"app.tasks.notify.Notify": mocker.MagicMock()},
        )

        res = NewUserActivatedTask().run_impl(
            dbsession, pull.repository.owner.ownerid, pull.author.ownerid
        )

        assert res == {
            "notifies_scheduled": True,
            "pulls_notified": [
                {"repoid": pull.repoid, "pullid": pull.pullid, "commitid": pull.head}
            ],
            "reason": None,
        }
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_called_with(
            kwargs=dict(commitid=pull.head, repoid=pull.repoid)
        )
