import pytest
from shared.billing import BillingPlan

from database.models import Owner, Repository
from database.tests.factories import OwnerFactory, RepositoryFactory
from services.github_marketplace import GitHubMarketplaceService
from tasks.github_marketplace import SyncPlansTask

# DONT WORRY, this is generated for the purposes of validation
# and is not the real one on which the code ran
fake_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQDCFqq2ygFh9UQU/6PoDJ6L9e4ovLPCHtlBt7vzDwyfwr3XGxln
0VbfycVLc6unJDVEGZ/PsFEuS9j1QmBTTEgvCLR6RGpfzmVuMO8wGVEO52pH73h9
rviojaheX/u3ZqaA0di9RKy8e3L+T0ka3QYgDx5wiOIUu1wGXCs6PhrtEwICBAEC
gYBu9jsi0eVROozSz5dmcZxUAzv7USiUcYrxX007SUpm0zzUY+kPpWLeWWEPaddF
VONCp//0XU8hNhoh0gedw7ZgUTG6jYVOdGlaV95LhgY6yXaQGoKSQNNTY+ZZVT61
zvHOlPynt3GZcaRJOlgf+3hBF5MCRoWKf+lDA5KiWkqOYQJBAMQp0HNVeTqz+E0O
6E0neqQDQb95thFmmCI7Kgg4PvkS5mz7iAbZa5pab3VuyfmvnVvYLWejOwuYSp0U
9N8QvUsCQQD9StWHaVNM4Lf5zJnB1+lJPTXQsmsuzWvF3HmBkMHYWdy84N/TdCZX
Cxve1LR37lM/Vijer0K77wAx2RAN/ppZAkB8+GwSh5+mxZKydyPaPN29p6nC6aLx
3DV2dpzmhD0ZDwmuk8GN+qc0YRNOzzJ/2UbHH9L/lvGqui8I6WLOi8nDAkEA9CYq
ewfdZ9LcytGz7QwPEeWVhvpm0HQV9moetFWVolYecqBP4QzNyokVnpeUOqhIQAwe
Z0FJEQ9VWsG+Df0noQJBALFjUUZEtv4x31gMlV24oiSWHxIRX4fEND/6LpjleDZ5
C/tY+lZIEO1Gg/FxSMB+hwwhwfSuE3WohZfEcSy+R48=
-----END RSA PRIVATE KEY-----"""


@pytest.mark.integration
class TestGHMarketplaceSyncPlansTask(object):
    def test_purchase_by_existing_owner(
        self, dbsession, mocker, mock_configuration, codecov_vcr
    ):
        mock_configuration.loaded_files[("github", "integration", "pem")] = (
            fake_private_key
        )

        mock_configuration.params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 51984,  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.params["services"]["github_marketplace"] = dict(
            use_stubbed=True
        )

        owner = OwnerFactory.create(
            username="cc-test",
            service="github",
            service_id="3877742",
            plan=None,
            plan_provider=None,
            plan_auto_activate=None,
            plan_user_count=None,
        )
        dbsession.add(owner)
        dbsession.flush()

        sender = {"login": "cc-test", "id": 3877742}
        account = {"type": "User", "id": 3877742, "login": "cc-test"}
        action = "purchased"

        task = SyncPlansTask()
        result = task.run_impl(dbsession, sender=sender, account=account, action=action)
        assert result["plan_type_synced"] == "paid"

        assert owner.plan == "users"
        assert owner.plan_provider == "github"
        assert owner.plan_auto_activate is True
        assert owner.plan_user_count == 10

    def test_purchase_new_owner(
        self, dbsession, mocker, mock_configuration, codecov_vcr
    ):
        mock_configuration.loaded_files[("github", "integration", "pem")] = (
            fake_private_key
        )

        mock_configuration.params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 51984,  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.params["services"]["github_marketplace"] = dict(
            use_stubbed=True
        )

        sender = {"login": "cc-test", "id": 3877742}
        account = {"type": "User", "id": 3877742, "login": "cc-test"}
        action = "purchased"

        task = SyncPlansTask()
        result = task.run_impl(dbsession, sender=sender, account=account, action=action)
        assert result["plan_type_synced"] == "paid"

        owner = (
            dbsession.query(Owner)
            .filter(Owner.service == "github", Owner.service_id == "3877742")
            .first()
        )

        assert owner is not None
        assert owner.username == "cc-test"
        assert owner.plan == "users"
        assert owner.plan_provider == "github"
        assert owner.plan_auto_activate is True
        assert owner.plan_user_count == 10

    def test_purchase_listing_not_found(
        self, dbsession, mocker, mock_configuration, codecov_vcr
    ):
        mock_configuration.loaded_files[("github", "integration", "pem")] = (
            fake_private_key
        )

        mock_configuration.params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 51984,  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.params["services"]["github_marketplace"] = dict(
            use_stubbed=True
        )

        sender = {"login": "cc-test", "id": 3877742}
        account = {"type": "Organization", "id": 123456, "login": "some-org"}
        action = "purchased"

        task = SyncPlansTask()
        result = task.run_impl(dbsession, sender=sender, account=account, action=action)
        assert result["plan_type_synced"] == "free"

        owner = (
            dbsession.query(Owner)
            .filter(Owner.service == "github", Owner.service_id == "123456")
            .first()
        )

        assert owner is not None
        assert owner.username == "some-org"
        assert owner.plan_provider == "github"
        assert owner.plan == BillingPlan.users_basic.value
        assert owner.plan_user_count == 1
        assert owner.plan_activated_users is None

    def test_cancelled(self, dbsession, mocker, mock_configuration, codecov_vcr):
        mock_configuration.loaded_files[("github", "integration", "pem")] = (
            fake_private_key
        )

        mock_configuration.params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 51984,  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.params["services"]["github_marketplace"] = dict(
            use_stubbed=True
        )

        owner = OwnerFactory.create(
            username="cc-test",
            service="github",
            service_id="3877742",
            plan="users",
            plan_provider="github",
            plan_auto_activate=True,
            plan_user_count=10,
        )
        dbsession.add(owner)
        repo_pub = RepositoryFactory.create(
            private=False,
            name="pub",
            using_integration=False,
            service_id="159090647",
            activated=True,
            owner=owner,
        )
        repo_pytest = RepositoryFactory.create(
            private=False,
            name="pytest",
            using_integration=False,
            service_id="159089634",
            activated=True,
            owner=owner,
        )
        repo_spack = RepositoryFactory.create(
            private=False,
            name="spack",
            using_integration=False,
            service_id="164948070",
            activated=True,
            owner=owner,
        )
        dbsession.add(repo_pub)
        dbsession.add(repo_pytest)
        dbsession.add(repo_spack)
        dbsession.flush()

        sender = {"login": "cc-test", "id": 3877742}
        account = {"type": "User", "id": 3877742, "login": "cc-test"}
        action = "cancelled"

        task = SyncPlansTask()
        result = task.run_impl(dbsession, sender=sender, account=account, action=action)
        assert result["plan_type_synced"] == "free"

        dbsession.commit()
        owner = (
            dbsession.query(Owner)
            .filter(Owner.service == "github", Owner.service_id == "3877742")
            .first()
        )
        assert owner is not None
        assert owner.username == "cc-test"
        assert owner.plan_provider == "github"
        assert owner.plan == "users-basic"
        assert owner.plan_user_count == 1
        assert owner.plan_activated_users is None

        repos = (
            dbsession.query(Repository)
            .filter(Repository.ownerid == owner.ownerid)
            .all()
        )
        assert len(repos) == 3
        for repo in repos:
            assert repo.activated is False

    def test_sync_all_plans(self, dbsession, mocker, mock_configuration, codecov_vcr):
        mock_configuration.loaded_files[("github", "integration", "pem")] = (
            fake_private_key
        )
        mock_configuration.params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 51984,  # Fake integration id, tested with a real one
            },
            "client_id": "testiouu71gdynyqxzk4",
            "client_secret": "3b4ab5b18be7155fdbb739e7f1ae277222fb12db",
        }
        mock_configuration.params["services"]["github_marketplace"] = dict(
            use_stubbed=True
        )

        # create owner whose plan is actually inactive
        owner = OwnerFactory.create(
            username="test2",
            service="github",
            service_id="781233",
            plan="users",
            plan_provider="github",
            plan_auto_activate=True,
            plan_user_count=10,
        )
        dbsession.add(owner)
        dbsession.flush()

        action = "purchased"
        ghm_service = GitHubMarketplaceService()

        SyncPlansTask().sync_all(dbsession, ghm_service=ghm_service, action=action)

        # inactive plan disabled
        dbsession.commit()
        assert owner.plan is None

        # active plans - service ids 2 and 4
        owners = dbsession.query(Owner).filter(Owner.service_id.in_(["2", "4"])).all()
        assert owners is not None
        for owner in owners:
            assert owner.plan == "users"
            assert owner.plan_provider == "github"
            assert owner.plan_auto_activate == True
            assert owner.plan_user_count == 12
