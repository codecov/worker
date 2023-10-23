from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx
import vcr
from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.torngit.exceptions import TorngitClientError

from database.models import Owner, Repository
from database.tests.factories import OwnerFactory, RepositoryFactory
from tasks.sync_repos import LIST_REPOS_GENERATOR_BY_OWNER_SLUG, SyncReposTask

here = Path(__file__)


class AsyncIterator:
    def __init__(self, seq):
        self.iter = iter(seq)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.iter)
        except StopIteration:
            raise StopAsyncIteration


def reuse_cassette(filepath):
    return vcr.use_cassette(
        filepath,
        record_mode="new_episodes",
        filter_headers=["authorization"],
        match_on=["method", "scheme", "host", "port", "path"],
    )


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
        assert new_entry.createstamp is None

    @pytest.mark.asyncio
    async def test_upsert_owner_update_existing(
        self, mocker, mock_configuration, dbsession
    ):
        ownerid = 1
        service = "github"
        service_id = "123456"
        old_username = "codecov_org"
        new_username = "Codecov"
        now = datetime.utcnow()
        existing_owner = OwnerFactory.create(
            ownerid=ownerid,
            organizations=[],
            service=service,
            username=old_username,
            permission=[],
            createstamp=now,
            service_id=service_id,
        )
        dbsession.add(existing_owner)
        dbsession.flush()

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
        assert updated_owner.createstamp == now

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_upsert_repo_update_existing(
        self, mocker, mock_configuration, dbsession, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        service = "gitlab"
        repo_service_id = "12071992"
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
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_upsert_repo_exists_but_wrong_owner(
        self, mocker, mock_configuration, dbsession, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        service = "gitlab"
        repo_service_id = "12071992"
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
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_upsert_repo_exists_both_wrong_owner_and_service_id(
        self, mocker, mock_configuration, dbsession, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        # It is unclear what situation leads to this
        # The most likely sitaution is that there was a repo abc on both owners kay and jay
        # Then kay deleted its own repo, and jay moved its own repo to kay ownership
        # Now the system sees that there is already a repo under kay with the right username
        # (kay) but the wrong service_id (since that's an old repo), and another repo
        # with the right service_id (because moved repos keep their service_ids) but wrong owner (jay)
        service = "gitlab"
        repository_name = "repository_name_hahahaha"
        repo_service_id = "12071992"
        wrong_service_id = "123498765482"
        repo_data = {
            "service_id": repo_service_id,
            "name": repository_name,
            "fork": None,
            "private": True,
            "language": None,
            "branch": b"master",
        }
        correct_owner = OwnerFactory.create(
            organizations=[], service=service, username="1nf1n1t3l00p", permission=[]
        )
        dbsession.add(correct_owner)
        dbsession.flush()
        repo_same_name = RepositoryFactory.create(
            private=True,
            name=repository_name,
            using_integration=False,
            service_id=wrong_service_id,
            owner=correct_owner,
        )
        dbsession.add(repo_same_name)
        wrong_owner = OwnerFactory.create(
            organizations=[], service=service, username="cc", permission=[]
        )
        dbsession.add(wrong_owner)
        right_service_id_repo = RepositoryFactory.create(
            private=True,
            name=repository_name,
            using_integration=False,
            service_id=repo_service_id,
            owner=wrong_owner,
        )
        dbsession.add(right_service_id_repo)
        dbsession.flush()

        upserted_repoid = SyncReposTask().upsert_repo(
            dbsession, service, correct_owner.ownerid, repo_data
        )

        assert upserted_repoid == right_service_id_repo.repoid
        assert (
            dbsession.query(Repository)
            .filter(
                Repository.ownerid == correct_owner.ownerid,
                Repository.service_id == repo_service_id,
            )
            .count()
        ) == 0  # We didn't move any repos or anything
        dbsession.refresh(right_service_id_repo)
        assert right_service_id_repo.name == repository_name
        assert right_service_id_repo.service_id == repo_service_id
        assert right_service_id_repo.ownerid == wrong_owner.ownerid
        dbsession.refresh(repo_same_name)
        assert repo_same_name.name == repository_name
        assert repo_same_name.service_id == wrong_service_id
        assert repo_same_name.ownerid == correct_owner.ownerid

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_upsert_repo_exists_but_wrong_service_id(
        self, mocker, mock_configuration, dbsession, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        service = "gitlab"
        repo_service_id = "12071992"
        repo_wrong_service_id = "40404"
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
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_upsert_repo_create_new(
        self, mocker, mock_configuration, dbsession, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        service = "gitlab"
        repo_service_id = "12071992"
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
        self, mocker, mock_configuration, dbsession, codecov_vcr, mock_redis
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
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_sync_repos_lock_error(
        self, mocker, mock_configuration, dbsession, mock_redis, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)
        dbsession.flush()
        mock_redis.lock.side_effect = LockError
        await SyncReposTask().run_async(
            dbsession, ownerid=user.ownerid, using_integration=False
        )
        assert user.permission == []  # there were no private repos to add

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_generator", [False, True])
    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_only_public_repos_not_in_db.yaml"
    )
    @respx.mock
    async def test_only_public_repos_not_in_db(
        self, mocker, mock_configuration, dbsession, mock_redis, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
            respx.post("https://api.github.com/graphql").mock(
                httpx.Response(
                    status_code=200,
                    content='{"data":{"viewer":{"repositories":{"totalCount": 1}}}}',
                    headers={"Content-Type": "application/json"},
                )
            )

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
    @pytest.mark.parametrize("use_generator", [False, True])
    @respx.mock
    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_sync_repos_using_integration.yaml"
    )
    async def test_sync_repos_using_integration(
        self,
        mocker,
        dbsession,
        mock_owner_provider,
        mock_redis,
        use_generator,
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
            respx.post("https://api.github.com/graphql").mock(
                httpx.Response(
                    status_code=200,
                    content='{"data":{"viewer":{"repositories":{"totalCount": 4}}}}',
                    headers={"Content-Type": "application/json"},
                )
            )

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

        def repo_obj(service_id, name, language, private, branch, using_integration):
            return {
                "owner": {
                    "service_id": "test-owner-service-id",
                    "username": "test-owner-username",
                },
                "repo": {
                    "service_id": service_id,
                    "name": name,
                    "language": language,
                    "private": private,
                    "branch": branch,
                },
                "_using_integration": using_integration,
            }

        mock_repos = [
            repo_obj("159089634", "pytest", "python", False, "main", True),
            repo_obj("164948070", "spack", "python", False, "develop", False),
            repo_obj("213786132", "pub", "dart", False, "master", None),
            repo_obj("555555555", "soda", "python", False, "main", None),
        ]

        # Mock GitHub response for repos that are visible to our app
        if use_generator:
            mock_owner_provider.list_repos_using_installation_generator.return_value = (
                AsyncIterator([mock_repos])
            )
        else:
            mock_owner_provider.list_repos_using_installation.return_value = mock_repos

        # Three of the four repositories we can see are already in the database.
        # Will we update `using_integration` correctly?
        preseeded_repos = []
        for repo in mock_repos[:-1]:
            preseeded_repos.append(
                RepositoryFactory.create(
                    private=repo["repo"]["private"],
                    name=repo["repo"]["name"],
                    using_integration=repo["_using_integration"],
                    service_id=repo["repo"]["service_id"],
                    owner=user,
                )
            )

        for repo in preseeded_repos:
            dbsession.add(repo)
        dbsession.flush()

        await SyncReposTask().run_async(
            dbsession, ownerid=user.ownerid, using_integration=True
        )
        dbsession.commit()

        repos = (
            dbsession.query(Repository)
            .filter(
                Repository.service_id.in_(
                    (repo["repo"]["service_id"] for repo in mock_repos)
                )
            )
            .all()
        )

        # We pre-seeded 3 repos in the database, but we should have added the
        # 4th based on our GitHub response
        assert len(repos) == 4

        assert user.permission == []  # there were no private repos
        for repo in repos:
            assert repo.using_integration is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_generator", [False, True])
    @respx.mock
    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_sync_repos_using_integration_no_repos.yaml"
    )
    async def test_sync_repos_using_integration_no_repos(
        self, mocker, mock_configuration, dbsession, mock_redis, use_generator
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
            respx.post("https://api.github.com/graphql").mock(
                httpx.Response(
                    status_code=200,
                    content='{"data":{"viewer":{"repositories":{"totalCount": 0}}}}',
                    headers={"Content-Type": "application/json"},
                )
            )

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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_sync_repos_no_github_access(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_owner_provider,
        mock_redis,
        use_generator,
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        token = "ecd73a086eadc85db68747a66bdbd662a785a072"
        repos = [RepositoryFactory.create(private=True) for _ in range(10)]
        dbsession.add_all(repos)
        dbsession.flush()
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            unencrypted_oauth_token=token,
            permission=sorted([r.repoid for r in repos]),
            service_id="45343385",
        )
        assert len(user.permission) > 0
        dbsession.add(user)
        dbsession.flush()
        mock_owner_provider.list_repos.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        await SyncReposTask().run_async(
            dbsession, ownerid=user.ownerid, using_integration=False
        )
        assert user.permission == []  # repos were removed

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_generator", [False, True])
    async def test_sync_repos_timeout(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_owner_provider,
        mock_redis,
        use_generator,
    ):
        if use_generator:
            mocker.patch.object(
                LIST_REPOS_GENERATOR_BY_OWNER_SLUG, "check_value", return_value=True
            )
        repos = [RepositoryFactory.create(private=True) for _ in range(10)]
        dbsession.add_all(repos)
        dbsession.flush()
        user = OwnerFactory.create(
            organizations=[], permission=sorted([r.repoid for r in repos])
        )
        assert len(user.permission) > 0
        dbsession.add(user)
        dbsession.flush()

        if use_generator:
            mock_owner_provider.list_repos_generator.side_effect = (
                SoftTimeLimitExceeded()
            )
        else:
            mock_owner_provider.list_repos.side_effect = SoftTimeLimitExceeded()

        with pytest.raises(SoftTimeLimitExceeded):
            await SyncReposTask().run_async(
                dbsession, ownerid=user.ownerid, using_integration=False
            )
        assert user.permission == sorted(
            [r.repoid for r in repos]
        )  # repos were removed
