import pytest
from asyncio import Future

from services.owner import get_owner_provider_service
from database.tests.factories import OwnerFactory


class TestOwnerServiceTestCase(object):

    def test_get_owner_provider_service(self, dbsession):
        owner = OwnerFactory.create(
            service='github',
            unencrypted_oauth_token='bcaa0dc0c66b4a8c8c65ac919a1a91aa',
            bot=None
        )
        dbsession.add(owner)
        dbsession.flush()
        res = get_owner_provider_service(owner)
        expected_data = {
            'owner': {
                'ownerid': owner.ownerid,
                'service_id': owner.service_id,
                'username': owner.username
            },
            'repo': {}
        }
        assert res.service == 'github'
        assert res.data == expected_data
        assert res.token == {'key': 'bcaa0dc0c66b4a8c8c65ac919a1a91aa', 'secret': None}

    def test_get_owner_provider_service_other_service(self, dbsession):
        owner = OwnerFactory.create(
            service='gitlab',
            unencrypted_oauth_token='testenll80qbqhofao65',
            bot=None
        )
        dbsession.add(owner)
        dbsession.flush()
        res = get_owner_provider_service(owner)
        expected_data = {
            'owner': {
                'ownerid': owner.ownerid,
                'service_id': owner.service_id,
                'username': owner.username
            },
            'repo': {}
        }
        assert res.service == 'gitlab'
        assert res.data == expected_data
        assert res.token == {'key': 'testenll80qbqhofao65', 'secret': None}

    def test_get_owner_provider_service_different_bot(self, dbsession):
        bot_token = 'bcaa0dc0c66b4a8c8c65ac919a1a91aa'
        owner = OwnerFactory.create(
            unencrypted_oauth_token='testyftq3ovzkb3zmt823u3t04lkrt9w',
            bot=OwnerFactory.create(
                unencrypted_oauth_token=bot_token,
            )
        )
        dbsession.add(owner)
        dbsession.flush()
        res = get_owner_provider_service(owner, using_integration=False)
        expected_data = {
            'owner': {
                'ownerid': owner.ownerid,
                'service_id': owner.service_id,
                'username': owner.username
            },
            'repo': {}
        }
        assert res.data['repo'] == expected_data['repo']
        assert res.data == expected_data
        assert res.token == {'key': bot_token, 'secret': None}
