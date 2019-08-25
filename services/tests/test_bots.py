import pytest

from tests.base import BaseTestCase
from services.bots import get_repo_appropriate_bot_token, RepositoryWithoutValidBotError
from database.tests.factories import RepositoryFactory, OwnerFactory


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

    def test_get_repo_appropriate_bot_token_repo_with_user_with_integration_bot_using_it(self, codecov_vcr):
        repo = RepositoryFactory.create(
            using_integration=True,
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
