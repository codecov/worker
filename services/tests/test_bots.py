from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories import OwnerFactory, RepositoryFactory
from helpers.exceptions import NoConfiguredAppsAvailable
from services.bots import (
    OwnerWithoutValidBotError,
    RepositoryWithoutValidBotError,
    TokenType,
    _get_installation_weight,
    get_owner_appropriate_bot_token,
    get_owner_installation_id,
    get_repo_appropriate_bot_token,
    get_repo_particular_bot_token,
    get_token_type_mapping,
)
from test_utils.base import BaseTestCase

# DONT WORRY, this is generated for the purposes of validation, and is not the real
# one on which the code ran
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


class TestBotsService(BaseTestCase):
    def test_get_repo_appropriate_bot_token_public_bot(self, mock_configuration):
        mock_configuration.set_params(
            {
                "github": {
                    "bot": {"key": "somekey"},
                    "bots": {
                        "tokenless": {"key": "sometokenlesskey", "username": "username"}
                    },
                }
            }
        )
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(service="github", unencrypted_oauth_token=None),
            ),
        )
        # It returns the owner, but in this case it's None
        expected_result = (
            {
                "key": "sometokenlesskey",
                "username": "username",
            },
            None,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_enterprise_yes_bot(
        self, mock_configuration, mocker
    ):
        mocker.patch("services.bots.is_enterprise", return_value=True)
        mock_configuration.set_params({"github": {"bot": {"key": "somekey"}}})
        repo = RepositoryFactory.create(
            private=True,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    service="github", unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        expected_result = ({"key": "somekey"}, None)
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_enterprise_no_bot(
        self, mock_configuration, mocker
    ):
        mocker.patch("services.bots.is_enterprise", return_value=True)
        repo = RepositoryFactory.create(
            private=True,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    service="github", unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        expected_result = (
            {
                "username": repo.bot.username,
                "key": "simple_code",
                "secret": None,
            },
            repo.bot,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_public_bot_without_key(
        self, mock_configuration
    ):
        mock_configuration.set_params({"github": {"bot": {"other": "field"}}})
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        expected_result = (
            {
                "username": repo.bot.username,
                "key": "simple_code",
                "secret": None,
            },
            repo.bot,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_valid_bot(self):

        repo = RepositoryFactory.create(
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        expected_result = (
            {
                "username": repo.bot.username,
                "key": "simple_code",
                "secret": None,
            },
            repo.bot,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_invalid_bot_valid_owner_bot(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token=None),
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        expected_result = (
            {
                "username": repo.owner.bot.username,
                "key": "now_that_code_is_complex",
                "secret": None,
            },
            repo.owner.bot,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_no_bot_valid_owner_bot(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        expected_result = (
            {
                "username": repo.owner.bot.username,
                "key": "now_that_code_is_complex",
                "secret": None,
            },
            repo.owner.bot,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_no_bot_invalid_owner_bot(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(unencrypted_oauth_token=None),
            ),
        )
        expected_result = (
            {
                "username": repo.owner.username,
                "key": "not_so_simple_code",
                "secret": None,
            },
            repo.owner,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_no_oauth_token_at_all(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(unencrypted_oauth_token=None),
            ),
        )
        with pytest.raises(RepositoryWithoutValidBotError):
            get_repo_appropriate_bot_token(repo)

    def test_get_repo_appropriate_bot_token_repo_with_user_with_integration_bot_not_using_it(
        self,
    ):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                integration_id="integration_id",
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(unencrypted_oauth_token=None),
            ),
        )
        expected_result = (
            {
                "username": repo.owner.username,
                "key": "not_so_simple_code",
                "secret": None,
            },
            repo.owner,
        )
        assert get_repo_appropriate_bot_token(repo) == expected_result

    @pytest.mark.integration
    def test_get_repo_appropriate_bot_token_repo_with_user_with_integration_bot_using_it(
        self, mock_configuration, codecov_vcr
    ):
        mock_configuration._params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 251234,  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.loaded_files[
            ("github", "integration", "pem")
        ] = fake_private_key
        repo = RepositoryFactory.create(
            using_integration=True,
            bot=None,
            owner=OwnerFactory.create(
                service="github",
                integration_id=1654873,  # 'ThiagoCodecov' integration id, for testing,
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(unencrypted_oauth_token=None),
            ),
        )
        expected_result = ({"key": "v1.test50wm4qyel2pbtpbusklcarg7c2etcbunnswp"}, None)
        installation_info = get_owner_installation_id(
            repo.owner, repo.using_integration, ignore_installation=False
        )
        assert installation_info == {"installation_id": 1654873}
        assert (
            get_repo_appropriate_bot_token(repo, installation_info) == expected_result
        )

    def test_get_repo_appropriate_bot_token_via_installation_covered_repo(
        self, mock_configuration, dbsession, mocker
    ):
        owner = OwnerFactory.create(
            service="github",
            integration_id=None,
            unencrypted_oauth_token="owner_token",
        )
        repo = RepositoryFactory(owner=owner, using_integration=False)
        installation = GithubAppInstallation(
            installation_id=12341234,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=None,  # all repos covered
            owner=owner,
        )
        dbsession.add(installation)
        dbsession.flush()

        assert owner.github_app_installations == [installation]
        assert installation.is_repo_covered_by_integration(repo)

        mock_get_github_integration_token = mocker.patch(
            "services.bots.get_github_integration_token",
            return_value="installation_token",
        )
        installation_info = get_owner_installation_id(
            repo.owner, repo.using_integration, ignore_installation=False
        )
        assert installation_info == {
            "installation_id": 12341234,
            "app_id": None,
            "pem_path": None,
            "fallback_installations": [],
        }
        response = get_repo_appropriate_bot_token(repo, installation_info)
        mock_get_github_integration_token.assert_called_with(
            "github", 12341234, app_id=None, pem_path=None
        )
        assert response == (
            {"key": "installation_token"},
            None,
        )

    def test_get_owner_appropriate_bot_token_owner_no_bot_no_integration(self):
        owner = OwnerFactory.create(
            unencrypted_oauth_token="owner_token", integration_id=None, bot=None
        )
        assert get_owner_appropriate_bot_token(owner, None) == {
            "key": "owner_token",
            "secret": None,
        }

    def test_get_owner_appropriate_bot_token_owner_has_bot_no_integration(self):
        owner = OwnerFactory.create(
            unencrypted_oauth_token="owner_token",
            integration_id=None,
            bot=OwnerFactory.create(unencrypted_oauth_token="bot_token"),
        )
        assert get_owner_appropriate_bot_token(owner, None) == {
            "key": "bot_token",
            "secret": None,
        }

    def test_get_owner_appropriate_bot_token_repo_with_no_oauth_token_at_all(self):
        owner = OwnerFactory.create(
            unencrypted_oauth_token=None,
            integration_id=None,
            bot=OwnerFactory.create(unencrypted_oauth_token=None),
        )
        with pytest.raises(OwnerWithoutValidBotError):
            get_owner_appropriate_bot_token(owner, None)

    def test_get_owner_appropriate_bot_token_with_user_with_integration_bot_using_it(
        self, mock_configuration, codecov_vcr
    ):
        mock_configuration._params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 251234,  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.loaded_files[
            ("github", "integration", "pem")
        ] = fake_private_key

        owner = OwnerFactory.create(
            service="github",
            integration_id=1654873,  # 'ThiagoCodecov' integration id, for testing,
            unencrypted_oauth_token="owner_token",
            bot=OwnerFactory.create(unencrypted_oauth_token=None),
        )

        expected_result = {"key": "v1.test50wm4qyel2pbtpbusklcarg7c2etcbunnswp"}
        integration_dict = get_owner_installation_id(
            owner, True, ignore_installation=False
        )
        assert (
            get_owner_appropriate_bot_token(owner, integration_dict) == expected_result
        )

    def test_get_owner_installation_id_no_installation_no_legacy_integration(
        self, mocker, dbsession
    ):
        owner = OwnerFactory(service="github", integration_id=None)
        assert owner.github_app_installations == []
        assert get_owner_installation_id(owner, True) is None

    def test_get_owner_installation_id_no_installation_yes_legacy_integration(
        self, mocker, dbsession
    ):
        owner = OwnerFactory(service="github", integration_id=12341234)
        assert owner.github_app_installations == []
        assert get_owner_installation_id(owner, True) == {"installation_id": 12341234}

    def test_get_owner_installation_id_yes_installation_yes_legacy_integration(
        self, mocker, dbsession
    ):
        owner = OwnerFactory(service="github", integration_id=12341234)
        installation = GithubAppInstallation(
            owner=owner,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=None,
            installation_id=123456,
        )
        dbsession.add(installation)
        dbsession.flush()
        assert owner.github_app_installations == [installation]
        assert get_owner_installation_id(owner, True) == {
            "installation_id": 123456,
            "app_id": None,
            "pem_path": None,
            "fallback_installations": [],
        }

    def test_get_owner_installation_id_yes_installation_yes_legacy_integration_yes_fallback(
        self, mocker, dbsession
    ):
        owner = OwnerFactory(service="github", integration_id=12341234)
        installation_0 = GithubAppInstallation(
            owner=owner,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=None,
            installation_id=123456,
        )
        installation_1 = GithubAppInstallation(
            owner=owner,
            name="my_app",
            repository_service_ids=None,
            installation_id=12000,
            app_id=1212,
            pem_path="path",
        )
        dbsession.add(installation_0)
        dbsession.flush()
        assert owner.github_app_installations == [installation_0, installation_1]
        assert get_owner_installation_id(owner, True, installation_name="my_app") == {
            "installation_id": 12000,
            "app_id": 1212,
            "pem_path": "path",
            "fallback_installations": [
                {"installation_id": 123456, "app_id": None, "pem_path": None}
            ],
        }

    def test_get_owner_installation_id_yes_installation_all_rate_limited(
        self, mocker, dbsession, mock_redis
    ):
        mock_redis.exists.return_value = True
        owner = OwnerFactory(service="github", integration_id=12341234)
        installation_0 = GithubAppInstallation(
            owner=owner,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=None,
            installation_id=123456,
        )
        installation_1 = GithubAppInstallation(
            owner=owner,
            name="my_app",
            repository_service_ids=None,
            installation_id=12000,
            app_id=1212,
            pem_path="path",
        )
        dbsession.add(installation_0)
        dbsession.flush()
        assert owner.github_app_installations == [installation_0, installation_1]
        with pytest.raises(NoConfiguredAppsAvailable):
            get_owner_installation_id(owner, True, installation_name="my_app")
        mock_redis.exists.assert_any_call(
            f"rate_limited_installations_{installation_0.id}"
        )
        mock_redis.exists.assert_any_call(
            f"rate_limited_installations_{installation_1.id}"
        )

    def test_get_owner_installation_id_yes_installation_yes_legacy_integration_specific_repos(
        self, mocker, dbsession
    ):
        owner = OwnerFactory(service="github", integration_id=12341234)
        repo_covered_by_installation = RepositoryFactory(
            owner=owner, using_integration=True
        )
        repo_not_covered_by_installation = RepositoryFactory(
            owner=owner, using_integration=True
        )
        installation = GithubAppInstallation(
            owner=owner,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=[repo_covered_by_installation.service_id],
            installation_id=123456,
            app_id=123,
            pem_path="some_path",
        )
        dbsession.add(installation)
        dbsession.flush()
        assert owner.github_app_installations == [installation]
        assert get_owner_installation_id(
            owner,
            repo_covered_by_installation.using_integration,
            repository=repo_covered_by_installation,
        ) == {
            "installation_id": 123456,
            "app_id": 123,
            "pem_path": "some_path",
            "fallback_installations": [],
        }
        # Notice that the installation object overrides the `Repository.using_integration` column completely
        # ^ Not true anymore. We decided against it because there are some edge cases in filling up the list
        assert get_owner_installation_id(
            owner,
            repo_not_covered_by_installation.using_integration,
            repository=repo_not_covered_by_installation,
        ) == {"installation_id": 12341234}

    @pytest.mark.parametrize(
        "time_edited_days,expected_weight",
        [(1, 26), (2, 52), (5, 152), (7, 296), (8, 448), (9, 728), (10, 1200)],
    )
    @freeze_time("2024-04-02 00:00:00")
    def test__get_installation_weight(
        self, time_edited_days, expected_weight, dbsession
    ):
        time_diff = datetime.now(timezone.utc) - timedelta(days=time_edited_days)
        owner = OwnerFactory(service="github", integration_id=12341234)
        installation = GithubAppInstallation(
            owner=owner,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=None,
            installation_id=123456,
            app_id=123,
            pem_path="some_path",
            created_at=time_diff,
            updated_at=time_diff,
        )
        dbsession.add(owner)
        dbsession.add(installation)
        dbsession.flush()
        assert _get_installation_weight(installation) == expected_weight

    @freeze_time("2024-04-02 00:00:00 UTC")
    def test_get_owner_installation_id_multiple_apps_weights(self, mocker, dbsession):
        """! This test is inherently flaky.
        We are testing the ramp up process for recently updated apps.
        installation_new should have a ~4% chance of being selected
        that is ~40 in 1000 selection we make.
        """
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        owner = OwnerFactory(service="github", integration_id=12341234)
        installation_old = GithubAppInstallation(
            owner=owner,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=None,
            installation_id=123456,
            app_id=123,
            pem_path="some_path",
            created_at=ten_days_ago,
            updated_at=ten_days_ago,
        )
        installation_new = GithubAppInstallation(
            owner=owner,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            repository_service_ids=None,
            installation_id=123000,
            app_id=456,
            pem_path="other_path",
            created_at=two_days_ago,
            updated_at=two_days_ago,
        )
        dbsession.add(owner)
        dbsession.add(installation_old)
        dbsession.add(installation_new)
        dbsession.flush()

        assert _get_installation_weight(installation_old) == 1200
        assert _get_installation_weight(installation_new) == 52
        choices = dict()
        choices[installation_old.installation_id] = 0
        choices[installation_new.installation_id] = 0
        # We select apps 1K times to reduce margin of test flakiness
        for _ in range(1000):
            installation_dict = get_owner_installation_id(owner, False)
            assert installation_dict is not None
            id_chosen = installation_dict["installation_id"]
            choices[id_chosen] += 1
        # Assert that both apps can be selected
        assert choices[installation_old.installation_id] > 0
        assert choices[installation_new.installation_id] > 0
        # Assert that the old app is selected more frequently
        assert (
            choices[installation_old.installation_id]
            > choices[installation_new.installation_id]
        )

    def test_get_token_type_mapping_public_repo_no_configuration_no_particular_bot(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params({"github": {"bot": {"key": "somekey"}}})
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token=None),
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(unencrypted_oauth_token=None),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        expected_result = {
            TokenType.admin: None,
            TokenType.read: None,
            TokenType.comment: None,
            TokenType.status: None,
            TokenType.tokenless: None,
        }
        assert expected_result == get_token_type_mapping(repo)

    def test_get_token_type_mapping_public_repo_only_tokenless_configuration_no_particular_bot(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "github": {
                    "bot": {"key": "somekey"},
                    "bots": {"tokenless": {"key": "sometokenlesskey"}},
                }
            }
        )
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token=None),
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(unencrypted_oauth_token=None),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        expected_result = {
            TokenType.admin: None,
            TokenType.read: None,
            TokenType.comment: None,
            TokenType.status: None,
            TokenType.tokenless: {"key": "sometokenlesskey"},
        }
        assert expected_result == get_token_type_mapping(repo)

    def test_get_token_type_mapping_public_repo_no_configuration(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params({"github": {"bot": {"key": "somekey"}}})
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        expected_result = {
            TokenType.admin: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.read: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.comment: None,
            TokenType.status: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.tokenless: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
        }

        assert expected_result == get_token_type_mapping(repo)

    def test_get_token_type_mapping_public_repo_some_configuration(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "github": {
                    "bot": {"key": "somekey"},
                    "bots": {
                        "read": {"key": "aaaa", "username": "aaaa"},
                        "status": {"key": "status", "username": "status"},
                        "comment": {"key": "nada"},
                    },
                }
            }
        )
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    service="github", unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        expected_result = {
            TokenType.admin: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.read: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.status: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.comment: {"key": "nada"},
            TokenType.tokenless: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
        }
        assert expected_result == get_token_type_mapping(repo)

    def test_get_token_type_mapping_public_repo_some_configuration_no_particular_bot(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "github": {
                    "bot": {"key": "somekey"},
                    "bots": {
                        "read": {"key": "aaaa", "username": "aaaa"},
                        "status": {"key": "status", "username": "status"},
                        "comment": {"key": "nada"},
                        "tokenless": {"key": "tokenlessKey"},
                    },
                }
            }
        )
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token=None),
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(service="github", unencrypted_oauth_token=None),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        expected_result = {
            TokenType.admin: None,
            TokenType.read: {"key": "aaaa", "username": "aaaa"},
            TokenType.status: {"key": "status", "username": "status"},
            TokenType.comment: {"key": "nada"},
            TokenType.tokenless: {"key": "tokenlessKey"},
        }
        assert expected_result == get_token_type_mapping(repo)

    def test_get_token_type_mapping_public_repo_some_configuration_not_github_no_particular_bot(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "github": {
                    "bot": {"key": "somekey"},
                    "bots": {
                        "read": {"key": "aaaa", "username": "aaaa"},
                        "status": {"key": "status", "username": "status"},
                        "comment": {"key": "nada"},
                    },
                },
                "bitbucket": {
                    "bot": {"key": "bit"},
                    "bots": {
                        "read": {"key": "bucket", "username": "bb"},
                        "comment": {"key": "bibu", "username": "cket"},
                        "tokenless": {"key": "tokenlessKey", "username": "aa"},
                    },
                },
            }
        )
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token=None),
            owner=OwnerFactory.create(
                service="bitbucket",
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(unencrypted_oauth_token=None),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        expected_result = {
            TokenType.admin: None,
            TokenType.read: {"key": "bucket", "username": "bb"},
            TokenType.comment: {"key": "bibu", "username": "cket"},
            TokenType.status: None,
            TokenType.tokenless: {"key": "tokenlessKey", "username": "aa"},
        }
        assert expected_result == get_token_type_mapping(repo)

    def test_get_token_type_mapping_public_repo_some_configuration_not_github(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "github": {
                    "bot": {"key": "somekey"},
                    "bots": {
                        "read": {"key": "aaaa", "username": "aaaa"},
                        "status": {"key": "status", "username": "status"},
                        "comment": {"key": "nada"},
                    },
                },
                "bitbucket": {
                    "bot": {"key": "bit"},
                    "bots": {
                        "read": {"key": "bucket", "username": "bb"},
                        "comment": {"key": "bibu", "username": "cket"},
                        "tokenless": {"key": "tokenlessKey", "username": "username"},
                    },
                },
            }
        )
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                service="bitbucket",
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        expected_result = {
            TokenType.admin: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.read: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.comment: {"key": "bibu", "username": "cket"},
            TokenType.status: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
            TokenType.tokenless: {
                "key": "simple_code",
                "secret": None,
                "username": repo.bot.username,
            },
        }
        assert expected_result == get_token_type_mapping(repo)

    def test_get_token_type_mapping_private_repo_no_configuration(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params({"github": {"bot": {"key": "somekey"}}})
        repo = RepositoryFactory.create(
            private=True,
            using_integration=False,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        assert get_token_type_mapping(repo) is None

    def test_get_token_type_mapping_public_repo_integration(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params({"github": {"bot": {"key": "somekey"}}})
        repo = RepositoryFactory.create(
            private=False,
            using_integration=True,
            bot=OwnerFactory.create(unencrypted_oauth_token="simple_code"),
            owner=OwnerFactory.create(
                unencrypted_oauth_token="not_so_simple_code",
                integration_id=90,
                bot=OwnerFactory.create(
                    unencrypted_oauth_token="now_that_code_is_complex"
                ),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        assert get_token_type_mapping(repo) is None

    def test_get_token_type_mapping_public_repo_no_integration_no_bot(
        self, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "github": {
                    "bots": {"read": {"key": "aaaa", "username": "aaaa"}},
                    "bot": {"key": "somekey"},
                }
            }
        )
        repo = RepositoryFactory.create(
            private=False,
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                service="github",
                unencrypted_oauth_token=None,
                integration_id=90,
                bot=OwnerFactory.create(service="github", unencrypted_oauth_token=None),
            ),
        )
        dbsession.add(repo)
        dbsession.flush()
        assert get_token_type_mapping(repo) == {
            TokenType.read: {"key": "aaaa", "username": "aaaa"},
            TokenType.admin: None,
            TokenType.comment: None,
            TokenType.status: None,
            TokenType.tokenless: None,
        }
