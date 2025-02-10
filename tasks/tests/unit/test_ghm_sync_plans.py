from freezegun import freeze_time
from shared.plan.constants import DEFAULT_FREE_PLAN

from database.models import Owner, Repository
from database.tests.factories import OwnerFactory, RepositoryFactory
from tasks.github_marketplace import SyncPlansTask


class TestGHMarketplaceSyncPlansTaskUnit(object):
    def test_create_or_update_to_free_plan_known_user(self, dbsession, mocker):
        owner = OwnerFactory.create(
            service="github",
            plan="users",
            plan_user_count=2,
            plan_activated_users=[1, 2],
        )
        dbsession.add(owner)
        repo = RepositoryFactory.create(
            private=True, service_id="12071992", activated=True, owner=owner
        )
        dbsession.add(repo)
        dbsession.flush()

        ghm_service = mocker.MagicMock(get_user=mocker.MagicMock())
        SyncPlansTask().create_or_update_to_free_plan(
            dbsession, ghm_service, owner.service_id
        )

        assert not ghm_service.get_user.called
        assert owner.plan == DEFAULT_FREE_PLAN
        assert owner.plan_user_count == 1
        assert owner.plan_activated_users is None

        dbsession.commit()
        # their repos should also be deactivated
        repos = (
            dbsession.query(Repository)
            .filter(Repository.ownerid == owner.ownerid)
            .all()
        )

        for repo in repos:
            assert repo.activated is False

    @freeze_time("2024-03-28T00:00:00")
    def test_create_or_update_to_free_plan_unknown_user(self, dbsession, mocker):
        service_id = "12345"
        username = "tomcat"
        name = "Tom Cat"
        email = "tom@cat.com"
        ghm_service = mocker.MagicMock(
            get_user=mocker.MagicMock(
                return_value=dict(login=username, name=name, email=email)
            )
        )
        SyncPlansTask().create_or_update_to_free_plan(
            dbsession, ghm_service, service_id
        )

        assert ghm_service.get_user.called

        owner = (
            dbsession.query(Owner)
            .filter(Owner.service_id == service_id, Owner.service == "github")
            .first()
        )
        assert owner.username == username
        assert owner.name == name
        assert owner.email == email
        assert owner.createstamp.isoformat() == "2024-03-28T00:00:00+00:00"

    def test_create_or_update_plan_known_user_with_plan(self, dbsession, mocker):
        owner = OwnerFactory.create(
            service="github",
            plan="users-basic",
            plan_user_count=10,
            plan_activated_users=[34123, 231, 2314212],
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
        )
        dbsession.add(owner)
        repo = RepositoryFactory.create(
            private=True, service_id="12071992", activated=True, owner=owner
        )
        dbsession.add(repo)
        dbsession.flush()

        stripe_mock = mocker.patch(
            "tasks.github_marketplace.stripe.Subscription.cancel"
        )
        ghm_service = mocker.MagicMock(get_user=mocker.MagicMock())
        SyncPlansTask().create_or_update_plan(
            dbsession, ghm_service, owner.service_id, dict(unit_count=5)
        )

        assert not ghm_service.get_user.called
        assert owner.plan == "users"
        assert owner.plan_provider == "github"
        assert owner.plan_auto_activate == True
        assert owner.plan_activated_users is None
        assert owner.plan_user_count == 5

        # stripe subscription should be canceled but not customer id
        stripe_mock.assert_called_with("sub_123", prorate=True)
        assert owner.stripe_subscription_id is None
        assert owner.stripe_customer_id == "cus_123"

    def test_create_or_update_plan_known_user_without_plan(self, dbsession, mocker):
        owner = OwnerFactory.create(
            service="github",
            plan=None,
            plan_user_count=None,
            plan_activated_users=None,
            stripe_customer_id=None,
            stripe_subscription_id=None,
        )
        dbsession.add(owner)
        repo = RepositoryFactory.create(
            private=True, service_id="12071992", activated=True, owner=owner
        )
        dbsession.add(repo)
        dbsession.flush()

        stripe_mock = mocker.patch(
            "tasks.github_marketplace.stripe.Subscription.cancel"
        )
        ghm_service = mocker.MagicMock(get_user=mocker.MagicMock())
        SyncPlansTask().create_or_update_plan(
            dbsession, ghm_service, owner.service_id, dict(unit_count=5)
        )

        assert not ghm_service.get_user.called
        assert owner.plan == "users"
        assert owner.plan_provider == "github"
        assert owner.plan_auto_activate == True
        assert owner.plan_activated_users is None
        assert owner.plan_user_count == 5

        stripe_mock.assert_not_called()
        assert owner.stripe_subscription_id is None
        assert owner.stripe_customer_id is None

    def test_create_or_update_plan_unknown_user(self, dbsession, mocker):
        service_id = "12345"
        username = "tomcat"
        name = "Tom Cat"
        email = "tom@cat.com"
        ghm_service = mocker.MagicMock(
            get_user=mocker.MagicMock(
                return_value=dict(login=username, name=name, email=email)
            )
        )
        SyncPlansTask().create_or_update_plan(
            dbsession, ghm_service, service_id, dict(unit_count=5)
        )

        assert ghm_service.get_user.called

        owner = (
            dbsession.query(Owner)
            .filter(Owner.service_id == service_id, Owner.service == "github")
            .first()
        )
        assert owner.username == username
        assert owner.name == name
        assert owner.email == email
        assert owner.plan == "users"
        assert owner.plan_provider == "github"
        assert owner.plan_auto_activate == True
        assert owner.plan_user_count == 5
