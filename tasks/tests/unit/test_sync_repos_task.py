import json
from pathlib import Path

import pytest

from tasks.sync_repos import SyncReposTask
from database.tests.factories import OwnerFactory, RepositoryFactory
from database.models import Owner, Repository

here = Path(__file__)


class TestSyncReposTaskUnit(object):
    @pytest.mark.asyncio
    async def test_unknown_owner(self, mocker, mock_configuration, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match="Owner not found"):
            await SyncReposTask().run_async(
                dbsession,
                ownerid=unknown_ownerid,
                username=None,
                using_integration=False,
            )

    @pytest.mark.asyncio
    async def test_upsert_owner_add_new(self, mocker, mock_configuration, dbsession):
        service = "github"
        service_id = "123456"
        username = "some_org"
        prev_entry = (
            dbsession.query(Owner)
            .filter(Owner.service == service, Owner.service_id == service_id)
            .first()
        )
        assert prev_entry is None

        upserted_ownerid = SyncReposTask().upsert_owner(
            dbsession, service, service_id, username
        )

        assert isinstance(upserted_ownerid, int)
        new_entry = (
            dbsession.query(Owner)
            .filter(Owner.service == service, Owner.service_id == service_id)
            .first()
        )
        assert new_entry is not None
        assert new_entry.username == username

    @pytest.mark.asyncio
    async def test_upsert_owner_update_existing(
        self, mocker, mock_configuration, dbsession
    ):
        ownerid = 1
        service = "github"
        service_id = "123456"
        old_username = "codecov_org"
        new_username = "Codecov"
        existing_owner = OwnerFactory.create(
            ownerid=ownerid,
            organizations=[],
            service=service,
            username=old_username,
            permission=[],
            service_id=service_id,
        )
        dbsession.add(existing_owner)

        upserted_ownerid = SyncReposTask().upsert_owner(
            dbsession, service, service_id, new_username
        )

        assert upserted_ownerid == ownerid
        updated_owner = (
            dbsession.query(Owner)
            .filter(Owner.service == service, Owner.service_id == service_id)
            .first()
        )
        assert updated_owner is not None
        assert updated_owner.username == new_username

    @pytest.mark.asyncio
    async def test_upsert_repo_update_existing(
        self, mocker, mock_configuration, dbsession
    ):
        service = "gitlab"
        repo_service_id = 12071992
        repo_data = {
            "service_id": repo_service_id,
            "name": "new-name",
            "fork": None,
            "private": True,
            "language": None,
            "branch": b"master",
        }

        # add existing to db
        user = OwnerFactory.create(
            organizations=[],
            service=service,
            username="1nf1n1t3l00p",
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)
        old_repo = RepositoryFactory.create(
            private=True,
            name="old-name",
            using_integration=False,
            service_id="12071992",
            owner=user,
        )
        dbsession.add(old_repo)
        dbsession.flush()

        upserted_repoid = SyncReposTask().upsert_repo(
            dbsession, service, user.ownerid, repo_data
        )

        assert upserted_repoid == old_repo.repoid
        updated_repo = (
            dbsession.query(Repository)
            .filter(
                Repository.ownerid == user.ownerid,
                Repository.service_id == str(repo_service_id),
            )
            .first()
        )
        assert updated_repo is not None
        assert updated_repo.private is True
        assert updated_repo.name == repo_data.get("name")
        assert updated_repo.updatestamp is not None
        assert updated_repo.deleted is False

    @pytest.mark.asyncio
    async def test_upsert_repo_exists_but_wrong_owner(
        self, mocker, mock_configuration, dbsession
    ):
        service = "gitlab"
        repo_service_id = 12071992
        repo_data = {
            "service_id": repo_service_id,
            "name": "pytest",
            "fork": None,
            "private": True,
            "language": None,
            "branch": b"master",
        }

        # setup db
        correct_owner = OwnerFactory.create(
            organizations=[],
            service=service,
            username="1nf1n1t3l00p",
            permission=[],
            service_id="45343385",
        )
        dbsession.add(correct_owner)
        wrong_owner = OwnerFactory.create(
            organizations=[],
            service=service,
            username="cc",
            permission=[],
            service_id="40404",
        )
        dbsession.add(wrong_owner)
        old_repo = RepositoryFactory.create(
            private=True,
            name="pytest",
            using_integration=False,
            service_id="12071992",
            owner=wrong_owner,
        )
        dbsession.add(old_repo)
        dbsession.flush()

        upserted_repoid = SyncReposTask().upsert_repo(
            dbsession, service, correct_owner.ownerid, repo_data
        )

        assert upserted_repoid == old_repo.repoid
        updated_repo = (
            dbsession.query(Repository)
            .filter(
                Repository.ownerid == correct_owner.ownerid,
                Repository.service_id == str(repo_service_id),
            )
            .first()
        )
        assert updated_repo is not None
        assert updated_repo.deleted is False
        assert updated_repo.updatestamp is not None

    @pytest.mark.asyncio
    async def test_upsert_repo_exists_but_wrong_service_id(
        self, mocker, mock_configuration, dbsession
    ):
        service = "gitlab"
        repo_service_id = 12071992
        repo_wrong_service_id = 40404
        repo_data = {
            "service_id": repo_service_id,
            "name": "pytest",
            "fork": None,
            "private": True,
            "language": None,
            "branch": b"master",
        }

        # setup db
        user = OwnerFactory.create(
            organizations=[],
            service=service,
            username="1nf1n1t3l00p",
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)

        old_repo = RepositoryFactory.create(
            private=True,
            name="pytest",
            using_integration=False,
            service_id=repo_wrong_service_id,
            owner=user,
        )
        dbsession.add(old_repo)
        dbsession.flush()

        upserted_repoid = SyncReposTask().upsert_repo(
            dbsession, service, user.ownerid, repo_data
        )

        assert upserted_repoid == old_repo.repoid

        updated_repo = (
            dbsession.query(Repository)
            .filter(
                Repository.ownerid == user.ownerid,
                Repository.service_id == str(repo_service_id),
            )
            .first()
        )
        assert updated_repo is not None
        assert updated_repo.service_id == str(repo_service_id)
        assert updated_repo.name == "pytest"

        bad_service_id_repo = (
            dbsession.query(Repository)
            .filter(
                Repository.ownerid == user.ownerid,
                Repository.service_id == str(repo_wrong_service_id),
            )
            .first()
        )
        assert bad_service_id_repo is None

    @pytest.mark.asyncio
    async def test_upsert_repo_create_new(self, mocker, mock_configuration, dbsession):
        service = "gitlab"
        repo_service_id = 12071992
        repo_data = {
            "service_id": repo_service_id,
            "name": "pytest",
            "fork": None,
            "private": True,
            "language": None,
            "branch": "master",
        }

        # setup db
        user = OwnerFactory.create(
            organizations=[],
            service=service,
            username="1nf1n1t3l00p",
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)
        dbsession.flush()

        upserted_repoid = SyncReposTask().upsert_repo(
            dbsession, service, user.ownerid, repo_data
        )

        assert isinstance(upserted_repoid, int)
        new_repo = (
            dbsession.query(Repository)
            .filter(
                Repository.ownerid == user.ownerid,
                Repository.service_id == str(repo_service_id),
            )
            .first()
        )
        assert new_repo is not None
        assert new_repo.name == repo_data.get("name")
        assert new_repo.language == repo_data.get("language")
        assert new_repo.branch == repo_data.get("branch")
        assert new_repo.private is True

    @pytest.mark.asyncio
    async def test_only_public_repos_already_in_db(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        token = "ecd73a086eadc85db68747a66bdbd662a785a072"
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            unencrypted_oauth_token=token,
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)

        repo_pub = RepositoryFactory.create(
            private=False,
            name="pub",
            using_integration=False,
            service_id="159090647",
            owner=user,
        )
        repo_pytest = RepositoryFactory.create(
            private=False,
            name="pytest",
            using_integration=False,
            service_id="159089634",
            owner=user,
        )
        repo_spack = RepositoryFactory.create(
            private=False,
            name="spack",
            using_integration=False,
            service_id="164948070",
            owner=user,
        )
        dbsession.add(repo_pub)
        dbsession.add(repo_pytest)
        dbsession.add(repo_spack)
        dbsession.flush()

        await SyncReposTask().run_async(
            dbsession, ownerid=user.ownerid, using_integration=False
        )
        repos = (
            dbsession.query(Repository)
            .filter(Repository.service_id.in_(("159090647", "159089634", "164948070")))
            .all()
        )

        assert user.permission == []  # there were no private repos to add
        assert len(repos) == 3

    @pytest.mark.asyncio
    async def test_only_public_repos_not_in_db(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        token = "ecd73a086eadc85db68747a66bdbd662a785a072"
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            unencrypted_oauth_token=token,
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)
        dbsession.flush()
        await SyncReposTask().run_async(
            dbsession, ownerid=user.ownerid, using_integration=False
        )

        public_repo_service_id = "159090647"
        expected_repo_service_ids = (public_repo_service_id,)
        assert user.permission == []  # there were no private repos to add
        repos = (
            dbsession.query(Repository)
            .filter(Repository.service_id.in_(expected_repo_service_ids))
            .all()
        )
        assert len(repos) == 1
        assert repos[0].service_id == public_repo_service_id
        assert repos[0].ownerid == user.ownerid

    @pytest.mark.asyncio
    async def test_sync_repos_using_integration(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        token = "ecd73a086eadc85db68747a66bdbd662a785a072"
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            unencrypted_oauth_token=token,
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)

        repo_pytest = RepositoryFactory.create(
            private=False,
            name="pytest",
            using_integration=False,
            service_id="159089634",
            owner=user,
        )
        repo_spack = RepositoryFactory.create(
            private=False,
            name="spack",
            using_integration=True,
            service_id="164948070",
            owner=user,
        )
        repo_pub = RepositoryFactory.create(
            private=False,
            name="pub",
            using_integration=None,
            service_id="213786132",
            owner=user,
        )
        dbsession.add(repo_pytest)
        dbsession.add(repo_spack)
        dbsession.add(repo_pub)
        dbsession.flush()

        await SyncReposTask().run_async(
            dbsession, ownerid=user.ownerid, using_integration=True
        )

        dbsession.commit()

        repos = (
            dbsession.query(Repository)
            .filter(
                Repository.service_id.in_(
                    (repo_pytest.service_id, repo_spack.service_id, repo_pub.service_id)
                )
            )
            .all()
        )
        assert len(repos) == 3

        assert user.permission == []  # there were no private repos
        for repo in repos:
            assert repo.using_integration is True

    @pytest.mark.asyncio
    async def test_sync_repos_using_integration_no_repos(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        token = "ecd73a086eadc85db68747a66bdbd662a785a072"
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            unencrypted_oauth_token=token,
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)

        repo_pytest = RepositoryFactory.create(
            private=False,
            name="pytest",
            using_integration=True,
            service_id="159089634",
            owner=user,
        )
        repo_spack = RepositoryFactory.create(
            private=False,
            name="spack",
            using_integration=True,
            service_id="164948070",
            owner=user,
        )
        dbsession.add(repo_pytest)
        dbsession.add(repo_spack)
        dbsession.flush()

        await SyncReposTask().run_async(
            dbsession, ownerid=user.ownerid, using_integration=True
        )

        dbsession.commit()

        repos = (
            dbsession.query(Repository)
            .filter(
                Repository.service_id.in_(
                    (repo_pytest.service_id, repo_spack.service_id)
                )
            )
            .all()
        )
        assert len(repos) == 2

        assert user.permission == []  # there were no private repos
        for repo in repos:
            # repos are no longer using integration
            assert repo.using_integration is False
