from services.repository import get_repo_provider_service
from database.tests.factories import RepositoryFactory, OwnerFactory


class TestRepositoryServiceTestCase(object):

    def test_get_repo_provider_service(self, dbsession):
        repo = RepositoryFactory.create(
            owner__unencrypted_oauth_token='testyftq3ovzkb3zmt823u3t04lkrt9w'
        )
        dbsession.add(repo)
        dbsession.flush()
        res = get_repo_provider_service(repo)
        expected_data = {
            'owner': {'ownerid': repo.owner.ownerid, 'service_id': None, 'username': repo.owner.username},
            'repo': {'name': 'example-python', 'using_integration': False},
            'yaml': {}
        }
        assert res.data == expected_data
        assert res.token == {'key': 'testyftq3ovzkb3zmt823u3t04lkrt9w', 'secret': None}

    def test_get_repo_provider_service_different_bot(self, dbsession):
        bot_token = 'bcaa0dc0c66b4a8c8c65ac919a1a91aa'
        bot = OwnerFactory.create(
            unencrypted_oauth_token=bot_token
        )
        repo = RepositoryFactory.create(
            owner__unencrypted_oauth_token='testyftq3ovzkb3zmt823u3t04lkrt9w',
            bot=bot
        )
        dbsession.add(repo)
        dbsession.add(bot)
        dbsession.flush()
        res = get_repo_provider_service(repo)
        expected_data = {
            'owner': {'ownerid': repo.owner.ownerid, 'service_id': None, 'username': repo.owner.username},
            'repo': {'name': 'example-python', 'using_integration': False},
            'yaml': {}
        }
        assert res.data == expected_data
        assert res.token == {'key': bot_token, 'secret': None}

    def test_get_repo_provider_service_no_bot(self, dbsession):
        bot_token = 'bcaa0dc0c66b4a8c8c65ac919a1a91aa'
        owner_bot = OwnerFactory.create(
            unencrypted_oauth_token=bot_token
        )
        repo = RepositoryFactory.create(
            owner__unencrypted_oauth_token='testyftq3ovzkb3zmt823u3t04lkrt9w',
            owner__bot=owner_bot,
            bot=None
        )
        dbsession.add(repo)
        dbsession.add(owner_bot)
        dbsession.flush()
        res = get_repo_provider_service(repo)
        expected_data = {
            'owner': {'ownerid': repo.owner.ownerid, 'service_id': None, 'username': repo.owner.username},
            'repo': {'name': 'example-python', 'using_integration': False},
            'yaml': {}
        }
        assert res.data == expected_data
        assert res.token == {'key': bot_token, 'secret': None}
