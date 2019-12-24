import json
from pathlib import Path
from asyncio import Future

import pytest

from tasks.delete_owner import DeleteOwnerTask
from database.tests.factories import OwnerFactory, RepositoryFactory, CommitFactory, BranchFactory, PullFactory
from database.models import Owner, Repository, Commit, Branch, Pull

here = Path(__file__)

class TestDeleteOwnerTaskUnit(object):

    @pytest.mark.asyncio
    async def test_unknown_owner(self, mocker, mock_configuration, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match='Owner not found'):
            await DeleteOwnerTask().run_async(
                dbsession,
                unknown_ownerid
            )

    @pytest.mark.asyncio
    async def test_delete_owner_deletes_owner_with_ownerid(self, mocker, mock_configuration, mock_storage, dbsession):
        ownerid = 10777
        serviceid = '12345'
        repoid = 1337

        user = OwnerFactory.create(
            ownerid=ownerid,
            service_id=serviceid
        )
        dbsession.add(user)

        repo = RepositoryFactory.create(
            repoid=repoid,
            name='dracula',
            service_id='7331',
            owner=user
        )
        dbsession.add(repo)

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner=user
        )
        dbsession.add(commit)

        branch = BranchFactory.create(
            repository=repo
        )
        dbsession.add(branch)

        pull = PullFactory.create(
            repository=repo
        )
        dbsession.add(pull)

        dbsession.flush()

        await DeleteOwnerTask().run_async(
            dbsession,
            ownerid
        )

        owner = dbsession.query(Owner).filter(
            Owner.ownerid == ownerid
        ).first()

        repos = dbsession.query(Repository).filter(
            Repository.ownerid == ownerid
        ).all()

        commits = dbsession.query(Commit).filter(
            Commit.repoid == repoid
        ).all()

        branches = dbsession.query(Branch).filter(
            Branch.repoid == repoid
        ).all()

        pulls = dbsession.query(Pull).filter(
            Pull.repoid == repoid
        ).all()

        assert owner is None
        assert repos == []
        assert commits == []
        assert branches == []
        assert pulls == []
