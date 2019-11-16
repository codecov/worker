import pytest

from tests.base import BaseTestCase
from services.bots import ( get_repo_appropriate_bot_token, RepositoryWithoutValidBotError,
    get_owner_appropriate_bot_token, OwnerWithoutValidBotError
)
from database.tests.factories import RepositoryFactory, OwnerFactory

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

    def test_get_repo_appropriate_bot_token_repo_with_valid_bot(self):

        repo = RepositoryFactory.create(
            using_integration=False,
            bot=OwnerFactory.create(
                unencrypted_oauth_token='simple_code'
            ),
            owner=OwnerFactory.create(
                unencrypted_oauth_token='not_so_simple_code',
                bot=OwnerFactory.create(
                    unencrypted_oauth_token='now_that_code_is_complex'
                )
            )
        )
        assert get_repo_appropriate_bot_token(repo) == {'key': 'simple_code', 'secret': None}

    def test_get_repo_appropriate_bot_token_repo_with_invalid_bot_valid_owner_bot(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=OwnerFactory.create(
                unencrypted_oauth_token=None
            ),
            owner=OwnerFactory.create(
                unencrypted_oauth_token='not_so_simple_code',
                bot=OwnerFactory.create(
                    unencrypted_oauth_token='now_that_code_is_complex'
                )
            )
        )
        expected_result = {'key': 'now_that_code_is_complex', 'secret': None}
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_no_bot_valid_owner_bot(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                unencrypted_oauth_token='not_so_simple_code',
                bot=OwnerFactory.create(
                    unencrypted_oauth_token='now_that_code_is_complex'
                )
            )
        )
        expected_result = {'key': 'now_that_code_is_complex', 'secret': None}
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_no_bot_invalid_owner_bot(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                unencrypted_oauth_token='not_so_simple_code',
                bot=OwnerFactory.create(
                    unencrypted_oauth_token=None
                )
            )
        )
        expected_result = {'key': 'not_so_simple_code', 'secret': None}
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_no_oauth_token_at_all(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                unencrypted_oauth_token=None,
                bot=OwnerFactory.create(
                    unencrypted_oauth_token=None
                )
            )
        )
        with pytest.raises(RepositoryWithoutValidBotError):
            get_repo_appropriate_bot_token(repo)

    def test_get_repo_appropriate_bot_token_repo_with_user_with_integration_bot_not_using_it(self):
        repo = RepositoryFactory.create(
            using_integration=False,
            bot=None,
            owner=OwnerFactory.create(
                integration_id='integration_id',
                unencrypted_oauth_token='not_so_simple_code',
                bot=OwnerFactory.create(
                    unencrypted_oauth_token=None
                )
            )
        )
        expected_result = {'key': 'not_so_simple_code', 'secret': None}
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_repo_appropriate_bot_token_repo_with_user_with_integration_bot_using_it(self, mock_configuration, codecov_vcr):
        mock_configuration._params['github'] = {
            'integration': {
                'pem': '/home/src/certs/github.pem',
                'id': 251234  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.loaded_files[('github', 'integration', 'pem')] = fake_private_key
        repo = RepositoryFactory.create(
            using_integration=True,
            bot=None,
            owner=OwnerFactory.create(
                service='github',
                integration_id=1654873,  # 'ThiagoCodecov' integration id, for testing,
                unencrypted_oauth_token='not_so_simple_code',
                bot=OwnerFactory.create(
                    unencrypted_oauth_token=None
                )
            )
        )
        expected_result = {
            'key': 'v1.test50wm4qyel2pbtpbusklcarg7c2etcbunnswp',
        }
        assert get_repo_appropriate_bot_token(repo) == expected_result

    def test_get_owner_appropriate_bot_token_owner_no_bot_no_integration(self):
        owner = OwnerFactory.create(
            unencrypted_oauth_token='owner_token',
            integration_id=None,
            bot=None
        )
        assert get_owner_appropriate_bot_token(owner, using_integration=False) == {'key': 'owner_token', 'secret': None}

    def test_get_owner_appropriate_bot_token_owner_has_bot_no_integration(self):
        owner = OwnerFactory.create(
            unencrypted_oauth_token='owner_token',
            integration_id=None,
            bot=OwnerFactory.create(
                unencrypted_oauth_token='bot_token'
            )
        )
        assert get_owner_appropriate_bot_token(owner, using_integration=False) == {'key': 'bot_token', 'secret': None}

    def test_get_owner_appropriate_bot_token_repo_with_no_oauth_token_at_all(self):
        owner = OwnerFactory.create(
            unencrypted_oauth_token=None,
            integration_id=None,
            bot=OwnerFactory.create(
                unencrypted_oauth_token=None
            )
        )
        with pytest.raises(OwnerWithoutValidBotError):
            get_owner_appropriate_bot_token(owner, using_integration=False)

    def test_get_owner_appropriate_bot_token_with_user_with_integration_bot_using_it(self, mock_configuration, codecov_vcr):
        mock_configuration._params['github'] = {
            'integration': {
                'pem': '/home/src/certs/github.pem',
                'id': 251234  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.loaded_files[('github', 'integration', 'pem')] = fake_private_key

        owner = OwnerFactory.create(
            service='github',
            integration_id=1654873,  # 'ThiagoCodecov' integration id, for testing,
            unencrypted_oauth_token='owner_token',
            bot=OwnerFactory.create(
                unencrypted_oauth_token=None
            )
        )

        expected_result = {
            'key': 'v1.test50wm4qyel2pbtpbusklcarg7c2etcbunnswp',
        }
        assert get_owner_appropriate_bot_token(owner, using_integration=True) == expected_result
