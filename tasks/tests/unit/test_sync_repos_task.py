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
            unencrypted_oauth_token=token,
            permission=[]
        )
        # repo = RepositoryFactory.create(
        #     private = False,
        #     name = 'pub',
        #     using_integration = False,
        #     service_id = 159090647,
        #     ownerid=user.ownerid
        # )
        dbsession.add(user)
        # dbsession.add(repo)
        dbsession.flush()
        await SyncReposTask().run_async(
            dbsession,
            user.ownerid,
            using_integration=False
        )
        assert len(user.permission) == 3