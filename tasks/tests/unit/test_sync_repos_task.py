import json
from pathlib import Path
from asyncio import Future

import pytest

from tasks.sync_repos import SyncReposTask
from database.tests.factories import OwnerFactory, RepositoryFactory
from database.models import Owner, Repository

here = Path(__file__)

class TestSyncReposTaskUnit(object):

    @pytest.mark.asyncio
    async def test_unknown_owner(self, mocker, mock_configuration, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match='Owner not found'):
            await SyncReposTask().run_async(
                dbsession,
                unknown_ownerid,
                username=None,
                using_integration=False
            )

    @pytest.mark.asyncio
    async def test_only_public_repos_already_in_db(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = 'ecd73a086eadc85db68747a66bdbd662a785a072'
        user = OwnerFactory.create(
            organizations=[],
            service='github',
            username='1nf1n1t3l00p',
            unencrypted_oauth_token=token,
            permission=[],
            service_id='45343385'
        )
        dbsession.add(user)

        repo_pub = RepositoryFactory.create(
            private=False,
            name='pub',
            using_integration=False,
            service_id='159090647',
            owner=user
        )
        repo_pytest = RepositoryFactory.create(
            private=False,
            name='pytest',
            using_integration=False,
            service_id='159089634',
            owner=user
        )
        repo_spack = RepositoryFactory.create(
            private=False,
            name='spack',
            using_integration=False,
            service_id='164948070',
            owner=user
        )
        dbsession.add(repo_pub)
        dbsession.add(repo_pytest)
        dbsession.add(repo_spack)
        dbsession.flush()

        await SyncReposTask().run_async(
            dbsession,
            user.ownerid,
            using_integration=False
        )
        repos = dbsession.query(Repository).filter(
            Repository.service_id.in_(('159090647', '159089634', '164948070'))
        ).all()
        for repo in repos:
            print(repo.__dict__)

        assert user.permission == [] # there were no private repos to add
        assert len(repos) == 3

    @pytest.mark.asyncio
    async def test_only_public_repos_not_in_db(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = 'ecd73a086eadc85db68747a66bdbd662a785a072'
        user = OwnerFactory.create(
            organizations=[],
            service='github',
            username='1nf1n1t3l00p',
            unencrypted_oauth_token=token,
            permission=[],
            service_id='45343385'
        )
        dbsession.add(user)
        dbsession.flush()
        await SyncReposTask().run_async(
            dbsession,
            user.ownerid,
            using_integration=False
        )

        public_repo_service_id = '159090647'
        expected_repo_service_ids = (public_repo_service_id,)
        assert user.permission == [] # there were no private repos to add
        repos = dbsession.query(Repository).filter(
            Repository.service_id.in_(expected_repo_service_ids)
        ).all()
        assert len(repos) == 1
        assert repos[0].service_id == public_repo_service_id
        assert repos[0].ownerid == user.ownerid