from sqlalchemy.orm.session import Session

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories.core import OwnerFactory, RepositoryFactory
from tasks.backfill_existing_gh_app_installations import (
    BackfillExistingIndividualGHAppInstallationTask,
)


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


class TestBackfillWithPreviousGHAppInstallation(object):
    def test_gh_app_with_selection_all(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner = OwnerFactory(service="github", integration_id=12345)
        gh_app_installation = GithubAppInstallation(
            owner=owner,
            repository_service_ids=None,
            installation_id=owner.integration_id,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        )

        dbsession.add_all([owner, gh_app_installation])
        dbsession.commit()

        # Mock fn return values
        mock_repo_provider.get_gh_app_installation.return_value = {
            "repository_selection": "all"
        }
        mocker.patch(
            "tasks.backfill_existing_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillExistingIndividualGHAppInstallationTask()
        assert task.run_impl(
            dbsession, gh_app_installation_id=gh_app_installation.id
        ) == {
            "successful": True,
            "reason": "backfill task finished",
        }

        gh_app_installation = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner.ownerid)
            .first()
        )
        assert gh_app_installation.owner == owner
        assert gh_app_installation.repository_service_ids is None

    def test_gh_app_with_specific_owner_ids(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner = OwnerFactory(service="github", integration_id=123)
        gh_app_installation = GithubAppInstallation(
            owner=owner,
            repository_service_ids=[237],
            installation_id=owner.integration_id,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        )

        owner_two = OwnerFactory(service="github", integration_id=456)
        gh_app_installation_two = GithubAppInstallation(
            owner=owner_two,
            repository_service_ids=[748],
            installation_id=owner_two.integration_id,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        )

        dbsession.add_all(
            [owner, gh_app_installation, owner_two, gh_app_installation_two]
        )
        dbsession.commit()

        # Mock fn return values
        mock_repo_provider.get_gh_app_installation.return_value = {
            "repository_selection": "all"
        }
        mocker.patch(
            "tasks.backfill_existing_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillExistingIndividualGHAppInstallationTask()
        assert task.run_impl(
            dbsession, gh_app_installation_id=gh_app_installation.id
        ) == {
            "successful": True,
            "reason": "backfill task finished",
        }

        db_gh_app_installation_one = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner.ownerid)
            .first()
        )
        assert db_gh_app_installation_one.owner == owner
        assert db_gh_app_installation_one.repository_service_ids is None

        # This one should have the same values as when it started
        db_gh_app_installation_two = (
            dbsession.query(GithubAppInstallation)
            .filter_by(ownerid=owner_two.ownerid)
            .first()
        )
        assert db_gh_app_installation_two.owner == owner_two
        assert (
            db_gh_app_installation_two.repository_service_ids
            == gh_app_installation_two.repository_service_ids
        )

    def test_gh_app_without_all_repo_selection(
        self, mocker, mock_repo_provider, dbsession: Session
    ):
        owner = OwnerFactory(service="github", integration_id=12345)
        gh_app_installation = GithubAppInstallation(
            owner=owner,
            repository_service_ids=None,
            installation_id=owner.integration_id,
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
            "tasks.backfill_existing_gh_app_installations.get_owner_provider_service",
            return_value=mock_repo_provider,
        )

        task = BackfillExistingIndividualGHAppInstallationTask()
        assert task.run_impl(
            dbsession, gh_app_installation_id=gh_app_installation.id
        ) == {
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
