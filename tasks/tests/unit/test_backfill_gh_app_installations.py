from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from shared.torngit.exceptions import TorngitError
from shared.utils.enums import TaskConfigGroup
from sqlalchemy.orm.session import Session

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Repository,
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
    async def test_backfill_no_github_service(self, dbsession: Session):
        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(dbsession, ownerid="123", service="gitlab") == {
            "successful": True,
            "reason": "no installation needed",
        }

    @pytest.mark.asyncio
    async def test_backfill_no_owner(self, dbsession: Session):
        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(dbsession, ownerid="123", service="github") == {
            "successful": False,
            "reason": "no owner found",
        }

    @pytest.mark.asyncio
    async def test_backfill_owner_with_no_installation_id(self, dbsession: Session):
        owner = OwnerFactory(service="github", integration_id=None)
        dbsession.add(owner)
        dbsession.commit()

        task = BackfillGHAppInstallationsTask()
        assert await task.run_async(
            dbsession, ownerid=owner.ownerid, service=owner.service
        ) == {"successful": True, "reason": "no installation needed"}


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
        assert await task.run_async(
            dbsession, ownerid=owner.ownerid, service=owner.service
        ) == {"successful": True, "reason": "successful backfill"}

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
        assert await task.run_async(
            dbsession, ownerid=owner.ownerid, service=owner.service
        ) == {"successful": True, "reason": "successful backfill"}

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
        assert await task.run_async(
            dbsession, ownerid=owner.ownerid, service=owner.service
        ) == {"successful": True, "reason": "selection is set to all"}

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
        assert await task.run_async(
            dbsession, ownerid=owner.ownerid, service=owner.service
        ) == {"successful": True, "reason": "successful backfill"}

        gh_app_installation = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner.ownerid)
            .first()
        )
        assert gh_app_installation.owner == owner
        # The +1 comes from the preexisting one, so we don't overwrite, we append
        assert len(gh_app_installation.repository_service_ids) == len(mock_repos) + 1

        for repo in mock_repos:
            assert (
                repo["repo"]["service_id"] in gh_app_installation.repository_service_ids
            )
