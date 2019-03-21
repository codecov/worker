from services.repository import get_repo_provider_service
from database.tests.factories import RepositoryFactory


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
            'yaml': None
        }
        assert res.data == expected_data
        assert res.token == {'key': 'testyftq3ovzkb3zmt823u3t04lkrt9w', 'secret': None}
