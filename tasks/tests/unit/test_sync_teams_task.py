import json
from pathlib import Path
from asyncio import Future

import pytest

from tasks.sync_teams import SyncTeamsTask
from database.tests.factories import OwnerFactory
from database.models import Owner

here = Path(__file__)

class TestSyncTeamsTaskUnit(object):

    @pytest.mark.asyncio
    async def test_unknown_owner(self, mocker, mock_configuration, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match='Owner not found'):
            await SyncTeamsTask().run_async(
                dbsession,
                unknown_ownerid,
                username=None,
                using_integration=False
            )

    @pytest.mark.asyncio
    async def test_no_teams(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = 'bcaa0dc0c66b4a8c8c65ac919a1a91aa'
        user = OwnerFactory.create(
            organizations=[],
            service='github',
            unencrypted_oauth_token=token
        )
        dbsession.add(user)
        dbsession.flush()
        await SyncTeamsTask().run_async(
            dbsession,
            user.ownerid,
            using_integration=False
        )
        assert user.organizations == []

    @pytest.mark.asyncio
    async def test_team_removed(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = 'bcaa0dc0c66b4a8c8c65ac919a1a91aa'
        prev_team = OwnerFactory.create(
            service='github',
            username='Evil_Corp',
        )
        dbsession.add(prev_team)
        user = OwnerFactory.create(
            organizations=[prev_team.ownerid],
            service='github',
            unencrypted_oauth_token=token
        )
        dbsession.add(user)
        dbsession.flush()
        await SyncTeamsTask().run_async(
            dbsession,
            user.ownerid,
            using_integration=False
        )
        assert prev_team.ownerid not in user.organizations

    @pytest.mark.asyncio
    async def test_team_data_updated(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = 'bcaa0dc0c66b4a8c8c65ac919a1a91aa'
        last_updated = '2018-06-01 01:02:30'
        old_team = OwnerFactory.create(
            service='github',
            service_id='8226205',
            username='cc_old',
            name='CODECOV_OLD',
            email='old@codecov.io',
            updatestamp=last_updated
        )
        dbsession.add(old_team)
        user = OwnerFactory.create(
            organizations=[],
            service='github',
            unencrypted_oauth_token=token
        )
        dbsession.add(user)
        dbsession.flush()

        await SyncTeamsTask().run_async(
            dbsession,
            user.ownerid,
            using_integration=False
        )
        assert old_team.ownerid in user.organizations

        # old team in db should have its data updated
        assert old_team.email == 'hello@codecov.io'
        assert old_team.username == 'codecov'
        assert old_team.name == 'Codecov'
        assert str(old_team.updatestamp) > last_updated

    @pytest.mark.asyncio
    async def test_gitlab_subgroups(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = 'testenll80qbqhofao65'
        user = OwnerFactory.create(
            organizations=[],
            service='gitlab',
            unencrypted_oauth_token=token
        )
        dbsession.add(user)
        dbsession.flush()
        await SyncTeamsTask().run_async(
            dbsession,
            user.ownerid,
            using_integration=False
        )

        assert len(user.organizations) == 6
        gitlab_groups = dbsession.query(Owner).filter(
            Owner.ownerid.in_(user.organizations)
        ).all()
        expected_owner_ids = [g.ownerid for g in gitlab_groups]
        assert sorted(user.organizations) == sorted(expected_owner_ids)

        expected_groups = {
            '4165904': {
                'username': 'l00p_group_1',
                'name': 'My Awesome Group',
                'parent_service_id': None
            },
            '4570068': {
                'username': 'falco-group-1',
                'name': 'falco-group-1',
                'parent_service_id': None
            },
            '4570071': {
                'username': 'falco-group-1:falco-subgroup-1',
                'name': 'falco-subgroup-1',
                'parent_service_id': '4570068'
            },
            '4165905': {
                'username': 'l00p_group_1:subgroup1',
                'name': 'subgroup1',
                'parent_service_id': '4165904'
            },
            '4165907': {
                'username': 'l00p_group_1:subgroup2',
                'name': 'subgroup2',
                'parent_service_id': '4165904'
            },
            '4255344': {
                'username': 'l00p_group_1:subgroup2:subsub',
                'name': 'subsub',
                'parent_service_id': '4165907'
            }
        }
        for g in gitlab_groups:
            service_id = g.service_id
            expected_data = expected_groups.get(service_id, {})
            assert g.username == expected_data.get('username')
            assert g.name == expected_data['name']
            if expected_data['parent_service_id']:
                assert g.parent_service_id == expected_data['parent_service_id']

