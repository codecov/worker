import pytest
from sqlalchemy.orm.session import Session

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Owner,
)
from database.tests.factories.core import OwnerFactory, RepositoryFactory
from tasks.backfill_gh_app_installations import BackfillGHAppInstallationsTask


def repo_obj(service_id, name, language, private, branch, using_integration):
    return {
        "owner": {
            "service_id": "test-owner-service-id",
            "username": "test-owner-username",
        },
        "repo": {
            "service_id": service_id,
            "name": name,
            "language": language,
            "private": private,
            "branch": branch,
        },
        "_using_integration": using_integration,
    }


class TestBackfillGHAppInstallationNoBackfill(object):
    @pytest.mark.asyncio
    async def test_backfill_owner_with_no_installation_id(self, dbsession: Session):
        owner = OwnerFactory(service="github", integration_id=None)
        dbsession.add(owner)
        dbsession.commit()

        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(dbsession, owner_ids=None) == {
            "successful": True,
            "reason": "backfill task finished",
        }

        owner = dbsession.query(Owner).filter(Owner.ownerid == owner.ownerid).first()
        assert owner.integration_id == None


class TestBackfillWithoutPreviousGHAppInstallation(object):
    @pytest.mark.asyncio
    async def test_no_previous_app_existing_repos_only(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner = OwnerFactory(service="github", integration_id=12345)
        dbsession.add(owner)

        # Create repos for mock endpoint and for DB
        mock_repos = [
            repo_obj("159089634", "pytest", "python", False, "main", True),
            repo_obj("164948070", "spack", "python", False, "develop", False),
            repo_obj("213786132", "pub", "dart", False, "master", None),
            repo_obj("555555555", "soda", "python", False, "main", None),
        ]
        for repo in mock_repos:
            repo_data = repo["repo"]
            dbsession.add(
                RepositoryFactory(
                    owner=owner,
                    name=repo_data["name"],
                    service_id=repo_data["service_id"],
                )
            )

        dbsession.commit()

        # Mock fn return values
        mock_repo_provider.list_repos_using_installation.return_value = mock_repos
        mocker.patch(
            f"tasks.backfill_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(dbsession, owner_ids=None) == {
            "successful": True,
            "reason": "backfill task finished",
        }

        new_gh_app_installation = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner.ownerid)
            .first()
        )
        assert new_gh_app_installation.owner == owner
        assert new_gh_app_installation.installation_id == owner.integration_id
        assert len(new_gh_app_installation.repository_service_ids) == len(mock_repos)

        for repo in mock_repos:
            assert (
                repo["repo"]["service_id"]
                in new_gh_app_installation.repository_service_ids
            )

    @pytest.mark.asyncio
    async def test_no_previous_app_some_existing_repos(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner = OwnerFactory(service="github", integration_id=12345)

        # Only one of the two mock repos is stored in the DB
        repo_name = "test-456"
        repo_service_id = "164948070"
        repo = RepositoryFactory(
            owner=owner, name=repo_name, service_id=repo_service_id
        )

        mock_repos = [
            repo_obj("159089634", "pytest", "python", False, "main", True),
            repo_obj(repo_service_id, repo_name, "python", False, "develop", False),
        ]

        dbsession.add_all([owner, repo])
        dbsession.commit()

        # Mock fn return values
        mock_repo_provider.list_repos_using_installation.return_value = mock_repos
        mocker.patch(
            f"tasks.backfill_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(dbsession, owner_ids=None) == {
            "successful": True,
            "reason": "backfill task finished",
        }

        new_gh_app_installation = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner.ownerid)
            .first()
        )
        assert new_gh_app_installation.owner == owner
        assert new_gh_app_installation.installation_id == owner.integration_id
        # Only added the service_id as long as the repository exists in our system as well
        assert len(new_gh_app_installation.repository_service_ids) == 1
        assert new_gh_app_installation.repository_service_ids[0] == repo_service_id


class TestBackfillWithPreviousGHAppInstallation(object):
    @pytest.mark.asyncio
    async def test_gh_app_with_selection_all(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner = OwnerFactory(service="github", integration_id=12345)
        gh_app_installation = GithubAppInstallation(
            owner=owner,
            repository_service_ids=[123],
            installation_id=123,
            # name would be set by the API
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        )

        dbsession.add_all([owner, gh_app_installation])
        dbsession.commit()

        # Mock fn return values
        mock_repo_provider.get_gh_app_installation.return_value = {
            "repository_selection": "all"
        }
        mocker.patch(
            f"tasks.backfill_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(dbsession, owner_ids=None) == {
            "successful": True,
            "reason": "backfill task finished",
        }

        gh_app_installation = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner.ownerid)
            .first()
        )
        assert gh_app_installation.owner == owner
        assert gh_app_installation.repository_service_ids == None

    @pytest.mark.asyncio
    async def test_gh_app_without_all_repo_selection(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner = OwnerFactory(service="github", integration_id=12345)
        gh_app_installation = GithubAppInstallation(
            owner=owner,
            repository_service_ids=["12345"],
            installation_id=123,
            # name would be set by the API
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        )

        # Create repos for mock endpoint and for DB
        mock_repos = [
            repo_obj("159089634", "pytest", "python", False, "main", True),
            repo_obj("164948070", "spack", "python", False, "develop", False),
            repo_obj("213786132", "pub", "dart", False, "master", None),
            repo_obj("555555555", "soda", "python", False, "main", None),
        ]
        for repo in mock_repos:
            repo_data = repo["repo"]
            dbsession.add(
                RepositoryFactory(
                    owner=owner,
                    name=repo_data["name"],
                    service_id=repo_data["service_id"],
                )
            )

        dbsession.add_all([owner, gh_app_installation])
        dbsession.commit()

        # Mock fn return values
        mock_repo_provider.get_gh_app_installation.return_value = {
            "repository_selection": "selected"
        }
        mock_repo_provider.list_repos_using_installation.return_value = mock_repos
        mocker.patch(
            f"tasks.backfill_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(dbsession, owner_ids=None) == {
            "successful": True,
            "reason": "backfill task finished",
        }

        gh_app_installation = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner.ownerid)
            .first()
        )
        assert gh_app_installation.owner == owner
        assert len(gh_app_installation.repository_service_ids) == len(mock_repos)

        for repo in mock_repos:
            assert (
                repo["repo"]["service_id"] in gh_app_installation.repository_service_ids
            )

    @pytest.mark.asyncio
    async def test_gh_app_with_provided_owner_ids(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner_one = OwnerFactory(service="github", integration_id=12345)
        gh_app_installation_one = GithubAppInstallation(
            owner=owner_one,
            repository_service_ids=["12345"],
            installation_id=owner_one.integration_id,
            # name would be set by the API
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        )
        # Another owner without gh app but with integration
        owner_without_gh_app = OwnerFactory(service="github", integration_id=128)
        repo_for_org_without_gh_app = RepositoryFactory(
            owner=owner_without_gh_app,
            name="test-123456",
            service_id="817235467",
        )

        # Create repos for mock endpoint and for DB
        mock_repos = [
            repo_obj("159089634", "pytest", "python", False, "main", True),
            repo_obj("164948070", "spack", "python", False, "develop", False),
            repo_obj("213786132", "pub", "dart", False, "master", None),
            repo_obj("555555555", "soda", "python", False, "main", None),
        ]
        for repo in mock_repos:
            repo_data = repo["repo"]
            dbsession.add(
                RepositoryFactory(
                    owner=owner_one,
                    name=repo_data["name"],
                    service_id=repo_data["service_id"],
                )
            )
        dbsession.add_all(
            [
                owner_one,
                gh_app_installation_one,
                owner_without_gh_app,
                repo_for_org_without_gh_app,
            ]
        )
        dbsession.commit()

        # Mock fn return values
        mock_repo_provider.get_gh_app_installation.return_value = {
            "repository_selection": "selected"
        }

        # Side effect returns a response for each time this mocked fn is called, so 1st time is mock_repos, 2nd time is the other
        mock_repo_provider.list_repos_using_installation.side_effect = [
            mock_repos,
            [
                repo_obj(
                    repo_for_org_without_gh_app.service_id,
                    repo_for_org_without_gh_app.name,
                    "python",
                    False,
                    "main",
                    None,
                )
            ],
        ]
        mocker.patch(
            f"tasks.backfill_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(
            dbsession, owner_ids=[owner_one.ownerid, owner_without_gh_app.ownerid]
        ) == {"successful": True, "reason": "backfill task finished"}

        gh_app_installation_one = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner_one.ownerid)
            .first()
        )
        assert gh_app_installation_one.owner == owner_one
        assert len(gh_app_installation_one.repository_service_ids) == len(mock_repos)

        for repo in mock_repos:
            assert (
                repo["repo"]["service_id"]
                in gh_app_installation_one.repository_service_ids
            )

        gh_app_installation_two = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner_without_gh_app.ownerid)
            .first()
        )
        assert gh_app_installation_two.owner == owner_without_gh_app
        assert (
            gh_app_installation_two.installation_id
            == owner_without_gh_app.integration_id
        )
        assert (
            gh_app_installation_two.repository_service_ids[0]
            == repo_for_org_without_gh_app.service_id
        )
