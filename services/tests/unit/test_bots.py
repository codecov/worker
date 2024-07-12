import datetime
from typing import List, Optional
from unittest.mock import patch

import pytest
from shared.bots import get_adapter_auth_information
from shared.bots.types import AdapterAuthInformation
from shared.torngit.base import TokenType
from shared.typings.oauth_token_types import Token
from shared.typings.torngit import GithubInstallationInfo
from shared.utils.test_utils import mock_config_helper

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories.core import OwnerFactory, RepositoryFactory


def get_github_integration_token_side_effect(
    service: str,
    installation_id: int = None,
    app_id: Optional[str] = None,
    pem_path: Optional[str] = None,
):
    return f"installation_token_{installation_id}_{app_id}"


# The tests for this fn also exist on shared. These, however, are testing the sqlalchemy implementation of them
class TestGettingAdapterAuthInformation(object):
    class TestGitHubOwnerNoRepoInfo(object):
        def _generate_test_owner(
            self,
            dbsession,
            *,
            with_bot: bool,
            integration_id: int | None = None,
            ghapp_installations: List[GithubAppInstallation] = None,
        ):
            if ghapp_installations is None:
                ghapp_installations = []
            owner = OwnerFactory(
                service="github",
                bot=None,
                unencrypted_oauth_token="owner_token: :refresh_token",
                integration_id=integration_id,
            )
            if with_bot:
                owner.bot = OwnerFactory(
                    service="github",
                    unencrypted_oauth_token="bot_token: :bot_refresh_token",
                )
            dbsession.add(owner)
            dbsession.flush()

            if ghapp_installations:
                for app in ghapp_installations:
                    app.owner = owner
                    dbsession.add(app)

            dbsession.flush()

            assert bool(owner.bot) == with_bot
            assert owner.github_app_installations == ghapp_installations

            return owner

        def test_select_owner_info(self, dbsession):
            owner = self._generate_test_owner(dbsession, with_bot=False)
            expected = AdapterAuthInformation(
                token=Token(
                    key="owner_token", refresh_token="refresh_token", secret=None
                ),
                token_owner=owner,
                selected_installation_info=None,
                fallback_installations=None,
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(owner) == expected

        def test_select_owner_bot_info(self, dbsession):
            owner = self._generate_test_owner(dbsession, with_bot=True)
            expected = AdapterAuthInformation(
                token=Token(
                    key="bot_token", refresh_token="bot_refresh_token", secret=None
                ),
                token_owner=owner.bot,
                selected_installation_info=None,
                fallback_installations=None,
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(owner) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_owner_single_installation(self, dbsession):
            installations = [
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1200,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=200,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                )
            ]
            owner = self._generate_test_owner(
                dbsession, with_bot=False, ghapp_installations=installations
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1200_200",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(
                    id=installations[0].id,
                    installation_id=1200,
                    app_id=200,
                    pem_path="pem_path",
                ),
                fallback_installations=[],
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(owner) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_owner_single_installation_ignoring_installations(
            self, dbsession
        ):
            installations = [
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1200,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=200,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                )
            ]
            owner = self._generate_test_owner(
                dbsession, with_bot=False, ghapp_installations=installations
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="owner_token", refresh_token="refresh_token", secret=None
                ),
                token_owner=owner,
                selected_installation_info=None,
                fallback_installations=None,
                token_type_mapping=None,
            )
            assert (
                get_adapter_auth_information(owner, ignore_installations=True)
                == expected
            )

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_owner_deprecated_using_integration(self, dbsession):
            owner = self._generate_test_owner(
                dbsession, with_bot=False, integration_id=1500
            )
            owner.oauth_token = None
            # Owner has no GithubApp, no token, and no bot configured
            # The integration_id is selected
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1500_None",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(installation_id=1500),
                fallback_installations=[],
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(owner) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_owner_multiple_installations_default_name(self, dbsession):
            installations = [
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1200,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=200,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
                # This should be ignored in the selection because of the name
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1300,
                    name="my_dedicated_app",
                    app_id=300,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
            ]
            owner = self._generate_test_owner(
                dbsession, with_bot=False, ghapp_installations=installations
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1200_200",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(
                    id=installations[0].id,
                    installation_id=1200,
                    app_id=200,
                    pem_path="pem_path",
                ),
                fallback_installations=[],
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(owner) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_owner_multiple_installations_custom_name(self, dbsession):
            installations = [
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1200,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=200,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
                # This should be selected first
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1300,
                    name="my_dedicated_app",
                    app_id=300,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
            ]
            owner = self._generate_test_owner(
                dbsession, with_bot=False, ghapp_installations=installations
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1300_300",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(
                    id=installations[1].id,
                    installation_id=1300,
                    app_id=300,
                    pem_path="pem_path",
                ),
                fallback_installations=[
                    GithubInstallationInfo(
                        id=installations[0].id,
                        installation_id=1200,
                        app_id=200,
                        pem_path="pem_path",
                    )
                ],
                token_type_mapping=None,
            )
            assert (
                get_adapter_auth_information(
                    owner, installation_name_to_use="my_dedicated_app"
                )
                == expected
            )

    class TestGitHubOwnerWithRepoInfo(object):
        def _generate_test_repo(
            self,
            dbsession,
            *,
            with_bot: bool,
            with_owner_bot: bool,
            integration_id: int | None = None,
            ghapp_installations: List[GithubAppInstallation] = None,
        ):
            if ghapp_installations is None:
                ghapp_installations = []
            owner = OwnerFactory(
                service="github",
                bot=None,
                unencrypted_oauth_token="owner_token: :refresh_token",
                integration_id=integration_id,
            )
            if with_owner_bot:
                owner.bot = OwnerFactory(
                    service="github",
                    unencrypted_oauth_token="bot_token: :bot_refresh_token",
                )
            dbsession.add(owner)
            dbsession.flush()

            if ghapp_installations:
                for app in ghapp_installations:
                    app.owner = owner
                    dbsession.add(app)

            dbsession.flush()

            repo = RepositoryFactory(
                owner=owner, using_integration=(integration_id is not None)
            )
            if with_bot:
                repo.bot = OwnerFactory(
                    service="github",
                    unencrypted_oauth_token="repo_bot_token: :repo_bot_refresh_token",
                )

            dbsession.add(repo)
            dbsession.flush()

            assert bool(owner.bot) == with_owner_bot
            assert bool(repo.bot) == with_bot
            assert owner.github_app_installations == ghapp_installations

            return repo

        def test_select_repo_info_fallback_to_owner(self, dbsession):
            repo = self._generate_test_repo(
                dbsession, with_bot=False, with_owner_bot=False
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="owner_token",
                    refresh_token="refresh_token",
                    secret=None,
                    username=repo.owner.username,
                ),
                token_owner=repo.owner,
                selected_installation_info=None,
                fallback_installations=None,
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(repo.owner, repo) == expected

        def test_select_owner_bot_info(self, dbsession):
            repo = self._generate_test_repo(
                dbsession, with_owner_bot=True, with_bot=False
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="bot_token",
                    refresh_token="bot_refresh_token",
                    secret=None,
                    username=repo.owner.bot.username,
                ),
                token_owner=repo.owner.bot,
                selected_installation_info=None,
                fallback_installations=None,
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(repo.owner, repo) == expected

        def test_select_repo_bot_info(self, dbsession):
            repo = self._generate_test_repo(
                dbsession, with_owner_bot=True, with_bot=True
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="repo_bot_token",
                    refresh_token="repo_bot_refresh_token",
                    secret=None,
                    username=repo.bot.username,
                ),
                token_owner=repo.bot,
                selected_installation_info=None,
                fallback_installations=None,
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(repo.owner, repo) == expected

        def test_select_repo_bot_info_public_repo(self, dbsession, mock_configuration):
            repo = self._generate_test_repo(
                dbsession, with_owner_bot=True, with_bot=True
            )
            mock_configuration.set_params(
                {
                    "github": {
                        "bot": {"key": "some_key"},
                        "bots": {
                            "read": {"key": "read_bot_key"},
                            "status": {"key": "status_bot_key"},
                            "comment": {"key": "commenter_bot_key"},
                        },
                    }
                }
            )
            repo.private = False

            repo_bot_token = Token(
                key="repo_bot_token",
                refresh_token="repo_bot_refresh_token",
                secret=None,
                username=repo.bot.username,
            )
            expected = AdapterAuthInformation(
                token=repo_bot_token,
                token_owner=repo.bot,
                selected_installation_info=None,
                fallback_installations=None,
                token_type_mapping={
                    TokenType.comment: Token(key="commenter_bot_key"),
                    TokenType.read: repo_bot_token,
                    TokenType.admin: repo_bot_token,
                    TokenType.status: repo_bot_token,
                    TokenType.tokenless: repo_bot_token,
                    TokenType.pull: repo_bot_token,
                    TokenType.commit: repo_bot_token,
                },
            )
            assert get_adapter_auth_information(repo.owner, repo) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_repo_single_installation(self, dbsession):
            installations = [
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1200,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=200,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                )
            ]
            repo = self._generate_test_repo(
                dbsession,
                with_bot=False,
                with_owner_bot=False,
                ghapp_installations=installations,
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1200_200",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(
                    id=installations[0].id,
                    installation_id=1200,
                    app_id=200,
                    pem_path="pem_path",
                ),
                fallback_installations=[],
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(repo.owner, repo) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_repo_deprecated_using_integration(self, dbsession):
            repo = self._generate_test_repo(
                dbsession, with_bot=False, integration_id=1500, with_owner_bot=False
            )
            repo.owner.oauth_token = None
            # Repo's owner has no GithubApp, no token, and no bot configured
            # The repo has not a bot configured
            # The integration_id is no longer verified
            # So we fail with exception
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1500_None",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(installation_id=1500),
                fallback_installations=[],
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(repo.owner, repo) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_repo_multiple_installations_default_name(self, dbsession):
            installations = [
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1200,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=200,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
                # This should be ignored in the selection because of the name
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1300,
                    name="my_dedicated_app",
                    app_id=300,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
            ]
            repo = self._generate_test_repo(
                dbsession,
                with_bot=False,
                with_owner_bot=False,
                ghapp_installations=installations,
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1200_200",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(
                    id=installations[0].id,
                    installation_id=1200,
                    app_id=200,
                    pem_path="pem_path",
                ),
                fallback_installations=[],
                token_type_mapping=None,
            )
            assert get_adapter_auth_information(repo.owner, repo) == expected

        @patch(
            "shared.bots.github_apps.get_github_integration_token",
            side_effect=get_github_integration_token_side_effect,
        )
        def test_select_repo_multiple_installations_custom_name(self, dbsession):
            installations = [
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1200,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=200,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
                # This should be selected first
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1300,
                    name="my_dedicated_app",
                    app_id=300,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                ),
            ]
            repo = self._generate_test_repo(
                dbsession,
                with_bot=False,
                with_owner_bot=False,
                ghapp_installations=installations,
            )
            expected = AdapterAuthInformation(
                token=Token(
                    key="installation_token_1300_300",
                ),
                token_owner=None,
                selected_installation_info=GithubInstallationInfo(
                    id=installations[1].id,
                    installation_id=1300,
                    app_id=300,
                    pem_path="pem_path",
                ),
                fallback_installations=[
                    GithubInstallationInfo(
                        id=installations[0].id,
                        installation_id=1200,
                        app_id=200,
                        pem_path="pem_path",
                    )
                ],
                token_type_mapping=None,
            )
            assert (
                get_adapter_auth_information(
                    repo.owner, repo, installation_name_to_use="my_dedicated_app"
                )
                == expected
            )

    @pytest.mark.parametrize("service", ["github", "gitlab"])
    def test_select_repo_public_with_no_token_no_admin_token_configured(
        self, service, dbsession, mocker
    ):
        repo = RepositoryFactory(owner__service=service, private=False)
        repo.owner.oauth_token = None
        dbsession.add(repo)
        dbsession.flush()
        mock_config_helper(
            mocker,
            configs={
                f"{service}.bots.tokenless": {"key": "tokenless_bot_token"},
                f"{service}.bots.comment": {"key": "commenter_bot_token"},
                f"{service}.bots.read": {"key": "reader_bot_token"},
                f"{service}.bots.status": {"key": "status_bot_token"},
            },
        )
        expected = AdapterAuthInformation(
            token=Token(key="tokenless_bot_token"),
            token_owner=None,
            selected_installation_info=None,
            fallback_installations=None,
            token_type_mapping={
                TokenType.comment: Token(key="commenter_bot_token"),
                TokenType.read: Token(key="reader_bot_token"),
                TokenType.admin: None,
                TokenType.status: Token(key="status_bot_token"),
                TokenType.tokenless: Token(key="tokenless_bot_token"),
                TokenType.pull: None,
                TokenType.commit: None,
            },
        )
        assert get_adapter_auth_information(repo.owner, repo) == expected
