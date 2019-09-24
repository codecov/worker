import pytest
from asyncio import Future

from services.repository import (
    get_repo_provider_service, fetch_appropriate_parent_for_commit, get_author_from_commit
)
from database.tests.factories import RepositoryFactory, OwnerFactory, CommitFactory


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
        }
        assert res.data == expected_data
        assert res.token == {'key': bot_token, 'secret': None}

    @pytest.mark.asyncio
    async def test_fetch_appropriate_parent_for_commit_grandparent(self, dbsession, mock_repo_provider):
        grandparent_commit_id = '8aa5aa054aaa21cf5a664acd504a1af6f5caafaa'
        parent_commit_id = 'a' * 32
        parent_commit = CommitFactory.create(
            commitid=grandparent_commit_id
        )
        commit = CommitFactory.create(
            parent_commit_id=None
        )
        f = Future()
        f.set_result({
            'commitid': commit.commitid,
            'parents': [
                {
                    'commitid': parent_commit_id,
                    'parents': [
                        {
                            'commitid': grandparent_commit_id,
                            'parents': []
                        }
                    ]
                }
            ]
        })
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        git_commit = {
            'parents': [parent_commit_id]
        }
        mock_repo_provider.get_ancestors_tree.return_value = f
        result = await fetch_appropriate_parent_for_commit(mock_repo_provider, commit, git_commit)
        assert grandparent_commit_id == result

    @pytest.mark.asyncio
    async def test_fetch_appropriate_parent_for_commit_direct_parent(self, dbsession, mock_repo_provider):
        parent_commit_id = '8aa5be054aeb21cf5a664ecd504a1af6f5ceafba'
        parent_commit = CommitFactory.create(
            commitid=parent_commit_id
        )
        commit = CommitFactory.create(
            parent_commit_id=None
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        git_commit = {
            'parents': [parent_commit_id]
        }
        expected_result = parent_commit_id
        result = await fetch_appropriate_parent_for_commit(mock_repo_provider, commit, git_commit)
        assert expected_result == result

    def test_get_author_from_commit_doesnt_exist(self, dbsession):
        service = 'github'
        author_id = '123'
        username = 'username'
        email = 'email'
        name = 'name'
        author = get_author_from_commit(dbsession, service, author_id, username, email, name)
        dbsession.flush()
        assert author.free == 0
        assert author is not None
        assert author.service == 'github'
        assert author.service_id == '123'
        assert author.name == 'name'
        assert author.email == 'email'
        assert author.username == 'username'
        assert author.plan_activated_users is None
        assert author.admins is None
        assert author.permission is None
        assert author.integration_id is None
        assert author.yaml is None
        assert author.oauth_token is None
        assert author.bot_id is None

    def test_get_author_from_commit_already_exists(self, dbsession):
        owner = OwnerFactory.create(
            service='bitbucket',
            service_id='975',
            email='different_email@email.com',
            username='whoknew',
            yaml=dict(a=['12', '3'])
        )
        dbsession.add(owner)
        dbsession.flush()
        service = 'bitbucket'
        author_id = '975'
        username = 'username'
        email = 'email'
        name = 'name'
        author = get_author_from_commit(dbsession, service, author_id, username, email, name)
        dbsession.flush()
        assert author.ownerid == owner.ownerid
        assert author.free == 0
        assert author is not None
        assert author.service == 'bitbucket'
        assert author.service_id == '975'
        assert author.name == owner.name
        assert author.email == 'different_email@email.com'
        assert author.username == 'whoknew'
        assert author.plan_activated_users == []
        assert author.admins == []
        assert author.permission == []
        assert author.integration_id is None
        assert author.yaml == {'a': ['12', '3']}
        assert author.oauth_token == owner.oauth_token
        assert author.bot_id == owner.bot_id
