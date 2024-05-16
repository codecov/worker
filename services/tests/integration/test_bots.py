import pytest
import requests

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories import RepositoryFactory
from helpers.exceptions import RepositoryWithoutValidBotError
from services.bots.github_apps import get_github_app_info_for_owner
from services.bots.repo_bots import get_repo_appropriate_bot_token

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


class TestRepositoryServiceIntegration(object):
    @pytest.mark.asyncio
    async def test_get_token_type_mapping_non_existing_integration(
        self, dbsession, codecov_vcr, mock_configuration, mocker
    ):
        # this test was done with valid integration_id, pem and then the data was scrubbed
        mocker.patch("shared.github.get_pem", return_value=fake_private_key)
        mock_configuration._params = {"github": {"integration": {"id": 123}}}
        repo = RepositoryFactory.create(
            owner__username="ThiagoCodecov",
            owner__service="github",
            owner__integration_id=5944641,
            name="example-python",
            using_integration=True,
            private=True,
        )
        repo.owner.oauth_token = None
        dbsession.add(repo)
        dbsession.flush()
        with pytest.raises(RepositoryWithoutValidBotError):
            get_repo_appropriate_bot_token(repo)

    @pytest.mark.asyncio
    async def test_get_token_type_mapping_bad_data(
        self, dbsession, codecov_vcr, mock_configuration, mocker
    ):
        mocker.patch("shared.github.get_pem", return_value=fake_private_key)
        mock_configuration._params = {"github": {"integration": {"id": 999}}}
        repo = RepositoryFactory.create(
            owner__username="ThiagoCodecov",
            owner__service="github",
            owner__integration_id=None,
            name="example-python",
            using_integration=False,
        )
        app = GithubAppInstallation(
            repository_service_ids=None,
            installation_id=5944641,
            app_id=999,
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            owner=repo.owner,
        )
        dbsession.add_all([repo, app])
        dbsession.flush()
        assert repo.owner.github_app_installations == [app]
        with pytest.raises(requests.exceptions.HTTPError):
            info = get_github_app_info_for_owner(repo.owner)
            get_repo_appropriate_bot_token(repo, info[0])
