from pathlib import Path

import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded

from database.models import Branch, Commit, CompareCommit, Owner, Pull, Repository
from database.tests.factories import (
    BranchFactory,
    CommitFactory,
    CompareCommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from services.archive import ArchiveService
from tasks.delete_owner import DeleteOwnerTask

here = Path(__file__)


class TestDeleteOwnerTaskUnit(object):
    def test_unknown_owner(self, mocker, mock_configuration, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match="Owner not found"):
            DeleteOwnerTask().run_impl(dbsession, unknown_ownerid)

    def test_delete_owner_deletes_owner_with_ownerid(
        self, mocker, mock_configuration, mock_storage, dbsession
    ):
        ownerid = 10777
        serviceid = "12345"
        repoid = 1337

        user = OwnerFactory.create(ownerid=ownerid, service_id=serviceid)
        dbsession.add(user)

        repo = RepositoryFactory.create(
            repoid=repoid, name="dracula", service_id="7331", owner=user
        )
        dbsession.add(repo)

        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner=user,
        )
        dbsession.add(commit)

        branch = BranchFactory.create(repository=repo)
        dbsession.add(branch)

        pull = PullFactory.create(repository=repo)
        dbsession.add(pull)

        dbsession.flush()

        DeleteOwnerTask().run_impl(dbsession, ownerid)

        owner = dbsession.query(Owner).filter(Owner.ownerid == ownerid).first()

        repos = dbsession.query(Repository).filter(Repository.ownerid == ownerid).all()

        commits = dbsession.query(Commit).filter(Commit.repoid == repoid).all()

        branches = dbsession.query(Branch).filter(Branch.repoid == repoid).all()

        pulls = dbsession.query(Pull).filter(Pull.repoid == repoid).all()

        assert owner is None
        assert repos == []
        assert commits == []
        assert branches == []
        assert pulls == []

    def test_delete_owner_deletes_owner_with_commit_compares(
        self, mocker, mock_configuration, mock_storage, dbsession
    ):
        ownerid = 10777
        serviceid = "12345"
        repoid = 1337

        user = OwnerFactory.create(ownerid=ownerid, service_id=serviceid)
        dbsession.add(user)

        repo = RepositoryFactory.create(
            repoid=repoid, name="dracula", service_id="7331", owner=user
        )
        dbsession.add(repo)

        base_commit_id = 1234
        base_commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner=user,
        )
        dbsession.add(base_commit)

        compare_commit_id = 1235
        compare_commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581421",
            repository__owner=user,
        )
        dbsession.add(compare_commit)

        comparison = CompareCommitFactory.create(
            base_commit=base_commit, compare_commit=compare_commit
        )
        dbsession.add(comparison)

        branch = BranchFactory.create(repository=repo)
        dbsession.add(branch)

        pull = PullFactory.create(repository=repo)
        dbsession.add(pull)

        dbsession.flush()

        DeleteOwnerTask().run_impl(dbsession, ownerid)

        owner = dbsession.query(Owner).filter(Owner.ownerid == ownerid).first()

        repos = dbsession.query(Repository).filter(Repository.ownerid == ownerid).all()

        commits = dbsession.query(Commit).filter(Commit.repoid == repoid).all()

        branches = dbsession.query(Branch).filter(Branch.repoid == repoid).all()

        pulls = dbsession.query(Pull).filter(Pull.repoid == repoid).all()

        comparisons = (
            dbsession.query(CompareCommit)
            .filter(
                CompareCommit.base_commit_id == base_commit_id
                or CompareCommit.compare_commit_id == compare_commit_id
            )
            .all()
        )

        assert owner is None
        assert repos == []
        assert commits == []
        assert branches == []
        assert pulls == []
        assert comparisons == []

    def test_delete_owner_from_orgs_removes_ownerid_from_organizations_of_related_owners(
        self, mocker, mock_configuration, mock_storage, dbsession
    ):
        org = OwnerFactory.create(service_id="9000")
        dbsession.add(org)
        dbsession.flush()
        org_ownerid = org.ownerid

        user_1 = OwnerFactory.create(
            ownerid=1001, service_id="9001", organizations=[org_ownerid]
        )
        dbsession.add(user_1)

        user_2 = OwnerFactory.create(
            ownerid=1002, service_id="9002", organizations=[org_ownerid, user_1.ownerid]
        )
        dbsession.add(user_2)

        dbsession.flush()

        DeleteOwnerTask().delete_owner_from_orgs(dbsession, org_ownerid)

        assert user_1.organizations == []
        assert user_2.organizations == [user_1.ownerid]

    def test_delete_owner_deletes_repo_archives_for_each_repo(
        self, mocker, mock_configuration, mock_storage, dbsession
    ):
        ownerid = 10777
        serviceid = "12345"

        user = OwnerFactory.create(ownerid=ownerid, service_id=serviceid)
        dbsession.add(user)

        repo_1 = RepositoryFactory.create(
            repoid=1337, name="dracula", service_id="7331", owner=user
        )
        dbsession.add(repo_1)

        repo_2 = RepositoryFactory.create(
            repoid=1338, name="frankenstein", service_id="7332", owner=user
        )
        dbsession.add(repo_2)

        dbsession.flush()

        mocked_delete_repo_files = mocker.patch.object(
            ArchiveService, "delete_repo_files"
        )

        DeleteOwnerTask().delete_repo_archives(dbsession, ownerid)

        assert mocked_delete_repo_files.call_count == 2

    def test_delete_owner_timeout(
        self, mocker, mock_configuration, mock_storage, dbsession
    ):
        org = OwnerFactory.create(service_id="9000")
        dbsession.add(org)

        dbsession.flush()
        mocker.patch.object(
            DeleteOwnerTask, "delete_repo_archives", side_effect=SoftTimeLimitExceeded()
        )
        with pytest.raises(Retry):
            DeleteOwnerTask().run_impl(dbsession, org.ownerid)
