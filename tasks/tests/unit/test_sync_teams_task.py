from pathlib import Path

import pytest
from freezegun import freeze_time

from database.models import Owner
from database.tests.factories import OwnerFactory
from tasks.sync_teams import SyncTeamsTask

here = Path(__file__)


class TestSyncTeamsTaskUnit(object):
    def test_unknown_owner(self, mocker, mock_configuration, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match="Owner not found"):
            SyncTeamsTask().run_impl(
                dbsession, unknown_ownerid, username=None, using_integration=False
            )

    def test_no_teams(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = "testv2ztxs03zwys22v36ama292esl13swroe6dj"
        user = OwnerFactory.create(
            organizations=[], service="github", unencrypted_oauth_token=token
        )
        dbsession.add(user)
        dbsession.flush()
        SyncTeamsTask().run_impl(dbsession, user.ownerid, using_integration=False)
        assert user.organizations == []

    def test_team_removed(self, mocker, mock_configuration, dbsession, codecov_vcr):
        token = "testv2ztxs03zwys22v36ama292esl13swroe6dj"
        prev_team = OwnerFactory.create(service="github", username="Evil_Corp")
        dbsession.add(prev_team)
        user = OwnerFactory.create(
            organizations=[prev_team.ownerid],
            service="github",
            unencrypted_oauth_token=token,
        )
        prev_team.plan_activated_users = [user.ownerid]
        dbsession.add(user)
        dbsession.flush()
        SyncTeamsTask().run_impl(dbsession, user.ownerid, using_integration=False)
        assert prev_team.ownerid not in user.organizations
        assert user.ownerid not in prev_team.plan_activated_users

    def test_team_data_updated(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        token = "testh0ry1fe5tiysbtbh6x47fdwotcsoyv7orqrd"
        last_updated = "2018-06-01 01:02:30"
        old_team = OwnerFactory.create(
            service="github",
            service_id="8226205",
            username="cc_old",
            name="CODECOV_OLD",
            email="old@codecov.io",
            updatestamp=last_updated,
        )
        dbsession.add(old_team)
        user = OwnerFactory.create(
            organizations=[], service="github", unencrypted_oauth_token=token
        )
        dbsession.add(user)
        dbsession.flush()

        SyncTeamsTask().run_impl(dbsession, user.ownerid, using_integration=False)
        assert old_team.ownerid in user.organizations

        # old team in db should have its data updated
        assert old_team.email is None
        assert old_team.username == "codecov"
        assert old_team.name == "codecov"
        assert str(old_team.updatestamp) > last_updated

    @freeze_time("2024-03-28T00:00:00")
    def test_gitlab_subgroups(
        self, mocker, mock_configuration, dbsession, codecov_vcr, caplog
    ):
        import logging

        caplog.set_level(logging.DEBUG)
        token = "testenll80qbqhofao65"
        user = OwnerFactory.create(
            organizations=[], service="gitlab", unencrypted_oauth_token=token
        )
        dbsession.add(user)
        dbsession.flush()
        SyncTeamsTask().run_impl(dbsession, user.ownerid, using_integration=False)

        assert len(user.organizations) == 6
        gitlab_groups = (
            dbsession.query(Owner).filter(Owner.ownerid.in_(user.organizations)).all()
        )
        expected_owner_ids = [g.ownerid for g in gitlab_groups]
        assert sorted(user.organizations) == sorted(expected_owner_ids)

        expected_groups = {
            "4165904": {
                "username": "l00p_group_1",
                "name": "My Awesome Group",
                "parent_service_id": None,
            },
            "4570068": {
                "username": "falco-group-1",
                "name": "falco-group-1",
                "parent_service_id": None,
            },
            "4570071": {
                "username": "falco-group-1:falco-subgroup-1",
                "name": "falco-subgroup-1",
                "parent_service_id": "4570068",
            },
            "4165905": {
                "username": "l00p_group_1:subgroup1",
                "name": "subgroup1",
                "parent_service_id": "4165904",
            },
            "4165907": {
                "username": "l00p_group_1:subgroup2",
                "name": "subgroup2",
                "parent_service_id": "4165904",
            },
            "4255344": {
                "username": "l00p_group_1:subgroup2:subsub",
                "name": "subsub",
                "parent_service_id": "4165907",
            },
        }
        for g in gitlab_groups:
            service_id = g.service_id
            expected_data = expected_groups.get(service_id, {})
            assert g.username == expected_data.get("username")
            assert g.name == expected_data["name"]
            assert g.createstamp.isoformat() == "2024-03-28T00:00:00+00:00"
            if expected_data["parent_service_id"]:
                assert g.parent_service_id == expected_data["parent_service_id"]
