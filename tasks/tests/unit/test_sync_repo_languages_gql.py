from datetime import datetime
from unittest.mock import Mock

from shared.torngit.exceptions import TorngitError, TorngitRateLimitError
from shared.utils.enums import TaskConfigGroup

from database.models.core import Repository
from database.tests.factories.core import OwnerFactory, RepositoryFactory
from tasks.sync_repo_languages_gql import SyncRepoLanguagesGQLTask


class TestSyncRepoLanguagesGQL(object):
    def test_get_repo_languages_without_org_or_current_owner(self, dbsession):
        task = SyncRepoLanguagesGQLTask()

        assert task.run_impl(dbsession, org_username="asdf", current_owner_id=123) == {
            "successful": False,
            "error": "no_owner_in_db",
        }

    def test_get_repo_languages_with_torngit_rate_limit_error(
        self, dbsession, mocker, mock_repo_provider
    ):
        current_owner = OwnerFactory.create(service="github")
        org = OwnerFactory.create(service="github")

        dbsession.add_all([current_owner, org])
        dbsession.flush()

        mocker.patch(
            f"tasks.{TaskConfigGroup.sync_repo_languages_gql.value}.get_owner_provider_service",
            return_value=mock_repo_provider,
        )
        mock_repo_provider.get_repos_with_languages_graphql = Mock(
            side_effect=TorngitRateLimitError("response_data", "message", "reset")
        )

        task = SyncRepoLanguagesGQLTask()

        assert task.run_impl(
            dbsession, org_username=org.username, current_owner_id=current_owner.ownerid
        ) == {"successful": False, "error": "torngit_rate_limit_error"}

    def test_get_repo_languages_with_torngit_error(
        self, dbsession, mocker, mock_repo_provider
    ):
        current_owner = OwnerFactory.create(service="github")
        org = OwnerFactory.create(service="github")

        dbsession.add_all([current_owner, org])
        dbsession.flush()

        mocker.patch(
            f"tasks.{TaskConfigGroup.sync_repo_languages_gql.value}.get_owner_provider_service",
            return_value=mock_repo_provider,
        )
        mock_repo_provider.get_repos_with_languages_graphql = Mock(
            side_effect=TorngitError()
        )

        task = SyncRepoLanguagesGQLTask()

        assert task.run_impl(
            dbsession, org_username=org.username, current_owner_id=current_owner.ownerid
        ) == {"successful": False, "error": "torngit_error"}

    def test_get_repo_languages_expected_response(
        self, dbsession, mocker, mock_repo_provider
    ):
        current_owner = OwnerFactory.create(service="github")
        org = OwnerFactory.create(service="github")

        repo_one_name = "test-one"
        repo_two_name = "test-two"
        repo_three_name = "test-three"

        repo_one = RepositoryFactory.create(name=repo_one_name, owner=org)
        repo_two = RepositoryFactory.create(
            name=repo_two_name, languages_last_updated=None, owner=org
        )
        repo_three = RepositoryFactory.create(name=repo_three_name, owner=org)

        dbsession.add_all([current_owner, org, repo_one, repo_two, repo_three])
        dbsession.flush()

        MOCKED_NOW = datetime(2024, 7, 3, 6, 8, 12)

        mock_return_value = {
            repo_one_name: ["javascript", "typescript"],
            repo_two_name: ["swift", "html"],
            repo_three_name: [],
            "random": ["python"],
        }

        mock_repo_provider.get_repos_with_languages_graphql.return_value = (
            mock_return_value
        )
        mocker.patch(
            f"tasks.{TaskConfigGroup.sync_repo_languages_gql.value}.get_owner_provider_service",
            return_value=mock_repo_provider,
        )
        mocker.patch(
            f"tasks.{TaskConfigGroup.sync_repo_languages_gql.value}.get_utc_now",
            return_value=MOCKED_NOW,
        )

        task = SyncRepoLanguagesGQLTask()

        assert task.run_impl(
            dbsession, org_username=org.username, current_owner_id=current_owner.ownerid
        ) == {"successful": True}

        all_repos = (
            dbsession.query(Repository)
            .filter(Repository.name.startswith("test-"))
            .all()
        )

        for repo in all_repos:
            assert repo.languages == mock_return_value[repo.name]
            assert repo.languages_last_updated == MOCKED_NOW
