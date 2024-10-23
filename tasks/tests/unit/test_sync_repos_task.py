from datetime import datetime
from pathlib import Path
from unittest.mock import call

import pytest
import respx
import vcr
from celery.exceptions import SoftTimeLimitExceeded
from freezegun import freeze_time
from redis.exceptions import LockError
from shared.celery_config import (
    sync_repo_languages_gql_task_name,
    sync_repo_languages_task_name,
)
from shared.torngit.exceptions import TorngitClientError, TorngitServer5xxCodeError

from database.models import Owner, Repository
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories import OwnerFactory, RepositoryFactory
from tasks.sync_repo_languages_gql import SyncRepoLanguagesGQLTask
from tasks.sync_repos import SyncReposTask

here = Path(__file__)


def reuse_cassette(filepath):
    return vcr.use_cassette(
        filepath,
        record_mode="new_episodes",
        filter_headers=["authorization"],
        match_on=["method", "scheme", "host", "port", "path"],
    )


class TestSyncReposTaskUnit(object):
    def test_unknown_owner(self, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match="Owner not found"):
            SyncReposTask().run_impl(
                dbsession,
                ownerid=unknown_ownerid,
                username=None,
                using_integration=False,
            )

    @freeze_time("2024-03-28T00:00:00")
    def test_upsert_owner_add_new(self, dbsession):
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
        assert new_entry.createstamp.isoformat() == "2024-03-28T00:00:00+00:00"

    def test_upsert_owner_update_existing(self, dbsession):
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

    def test_upsert_repo_update_existing(
        self,
        dbsession,
    ):
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

    def test_upsert_repo_exists_but_wrong_owner(self, dbsession):
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

    def test_upsert_repo_exists_both_wrong_owner_and_service_id(self, dbsession):
        # It is unclear what situation leads to this
        # The most likely situation is that there was a repo abc on both owners kay and jay
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

    def test_upsert_repo_exists_but_wrong_service_id(self, dbsession):
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

    def test_upsert_repo_create_new(self, dbsession):
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

    @pytest.mark.django_db(databases={"default"})
    def test_only_public_repos_already_in_db(self, dbsession):
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

        SyncReposTask().run_impl(
            dbsession, ownerid=user.ownerid, using_integration=False
        )
        repos = (
            dbsession.query(Repository)
            .filter(Repository.service_id.in_(("159090647", "159089634", "164948070")))
            .all()
        )

        assert user.permission == []  # there were no private repos to add
        assert len(repos) == 3

    def test_sync_repos_lock_error(self, dbsession, mock_redis):
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
        SyncReposTask().run_impl(
            dbsession, ownerid=user.ownerid, using_integration=False
        )
        assert user.permission == []  # there were no private repos to add

    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_only_public_repos_not_in_db.yaml"
    )
    @respx.mock
    @pytest.mark.django_db(databases={"default"})
    def test_only_public_repos_not_in_db(self, dbsession):
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
        SyncReposTask().run_impl(
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

    @respx.mock
    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_sync_repos_using_integration.yaml"
    )
    @pytest.mark.django_db(databases={"default"})
    def test_sync_repos_using_integration(
        self,
        mocker,
        dbsession,
        mock_owner_provider,
        mock_redis,
    ):
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)

        mock_redis.exists.return_value = False
        mocker.patch(
            "shared.bots.github_apps.get_github_integration_token",
            return_value="installation_token",
        )

        ghapp = GithubAppInstallation(
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            installation_id=1822,
            # inaccurate because this integration should be able to list all repos in the test
            # but the sync_repos should fix this too
            repository_service_ids=["555555555"],
            owner=user,
        )
        dbsession.add(ghapp)
        user.github_app_installations = [ghapp]

        dbsession.flush()

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
        mock_owner_provider.list_repos_using_installation_generator.return_value.__aiter__.return_value = [
            mock_repos
        ]

        # Three of the four repositories we can see are already in the database.
        # Will we update `using_integration` correctly?
        preseeded_repos = [
            RepositoryFactory.create(
                private=repo["repo"]["private"],
                name=repo["repo"]["name"],
                using_integration=repo["_using_integration"],
                service_id=repo["repo"]["service_id"],
                owner=user,
            )
            for repo in mock_repos[:-1]
        ]

        for repo in preseeded_repos:
            dbsession.add(repo)
        dbsession.flush()

        SyncReposTask().run_impl(
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
        ghapp.repository_service_ids = ["159089634" "164948070" "213786132" "555555555"]

    @respx.mock
    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_sync_repos_using_integration_no_repos.yaml"
    )
    def test_sync_repos_using_integration_no_repos(
        self,
        dbsession,
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

        SyncReposTask().run_impl(
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

    @pytest.mark.parametrize(
        "list_repos_error",
        [
            TorngitClientError("code", "response", "message"),
            TorngitServer5xxCodeError("5xx error"),
            SoftTimeLimitExceeded(),
        ],
    )
    def test_sync_repos_list_repos_error(
        self,
        dbsession,
        mock_owner_provider,
        list_repos_error,
    ):
        token = "ecd73a086eadc85db68747a66bdbd662a785a072"
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            unencrypted_oauth_token=token,
            service_id="45343385",
        )
        dbsession.add(user)
        dbsession.flush()

        repos = [RepositoryFactory.create(private=True, owner=user) for _ in range(10)]
        dbsession.add_all(repos)
        dbsession.flush()

        user.permission = sorted([r.repoid for r in repos])
        assert len(user.permission) > 0
        dbsession.flush()

        list_repos_result = [
            dict(
                owner=dict(
                    service_id=repo.owner.service_id,
                    username=repo.owner.username,
                ),
                repo=dict(
                    service_id=repo.service_id,
                    name=repo.name,
                    language=repo.language,
                    private=repo.private,
                    branch=repo.branch or "master",
                ),
            )
            for repo in repos
        ]

        # Yield the first page of repos and then throw an error
        async def mock_list_repos_generator(*args, **kwargs):
            yield list_repos_result[:5]
            raise list_repos_error

        mock_owner_provider.list_repos_generator = mock_list_repos_generator

        SyncReposTask().run_impl(
            dbsession, ownerid=user.ownerid, using_integration=False
        )

        # `list_repos()` raised an error so we couldn't finish every repo, but the first page was finished and should show up here.
        assert user.permission == sorted([r.repoid for r in repos[:5]])

    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_only_public_repos_not_in_db.yaml"
    )
    @respx.mock
    def test_insert_repo_and_call_repo_sync_languages(self, dbsession):
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
        SyncReposTask().run_impl(
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

    @respx.mock
    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_sync_repos_using_integration.yaml"
    )
    def test_insert_repo_and_call_repo_sync_languages_using_integration(
        self,
        mocker,
        dbsession,
        mock_owner_provider,
    ):
        mocked_app = mocker.patch.object(
            SyncReposTask,
            "app",
            tasks={
                sync_repo_languages_task_name: mocker.MagicMock(),
            },
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
        mock_owner_provider.list_repos_using_installation_generator.return_value.__aiter__.return_value = [
            mock_repos
        ]

        # Three of the four repositories we can see are already in the database.
        # Will we update `using_integration` correctly?
        preseeded_repos = [
            RepositoryFactory.create(
                private=repo["repo"]["private"],
                name=repo["repo"]["name"],
                using_integration=repo["_using_integration"],
                service_id=repo["repo"]["service_id"],
                owner=user,
            )
            for repo in mock_repos[:-1]
        ]

        for repo in preseeded_repos:
            dbsession.add(repo)
        dbsession.flush()

        SyncReposTask().run_impl(
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

        new_repo_list = list(set(repos) - set(preseeded_repos))

        mocked_app.tasks[sync_repo_languages_task_name].apply_async.assert_any_call(
            kwargs={"repoid": new_repo_list[0].repoid, "manual_trigger": False}
        )

    @respx.mock
    @reuse_cassette(
        "tasks/tests/unit/cassetes/test_sync_repos_task/TestSyncReposTaskUnit/test_sync_repos_using_integration.yaml"
    )
    def test_insert_repo_and_not_call_repo_sync_languages_using_integration(
        self,
        mocker,
        dbsession,
        mock_owner_provider,
    ):
        mocked_app = mocker.patch.object(
            SyncReposTask,
            "app",
            tasks={
                sync_repo_languages_task_name: mocker.MagicMock(),
            },
        )

        mocker.patch("tasks.sync_repos.get_config", return_value=False)

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
        ]
        mock_owner_provider.list_repos_using_installation_generator.return_value.__aiter__.return_value = [
            mock_repos
        ]

        preseeded_repos = [
            RepositoryFactory.create(
                private=repo["repo"]["private"],
                name=repo["repo"]["name"],
                using_integration=repo["_using_integration"],
                service_id=repo["repo"]["service_id"],
                owner=user,
            )
            for repo in mock_repos[:-1]
        ]

        for repo in preseeded_repos:
            dbsession.add(repo)
        dbsession.flush()

        SyncReposTask().run_impl(
            dbsession, ownerid=user.ownerid, using_integration=True
        )

        mocked_app.tasks[sync_repo_languages_task_name].apply_async.assert_not_called()

    def test_sync_repos_using_integration_affected_repos_known(
        self,
        mocker,
        dbsession,
        mock_owner_provider,
        mock_redis,
    ):
        user = OwnerFactory.create(
            organizations=[],
            service="github",
            username="1nf1n1t3l00p",
            unencrypted_oauth_token="sometesttoken",
            permission=[],
            service_id="45343385",
        )
        dbsession.add(user)

        mocked_app = mocker.patch.object(
            SyncRepoLanguagesGQLTask,
            "app",
            tasks={
                sync_repo_languages_gql_task_name: mocker.MagicMock(),
            },
        )
        repository_service_ids = [
            ("460565350", "R_kgDOG3OrZg"),
            ("665728948", "R_kgDOJ643tA"),
            ("553624697", "R_kgDOIP-keQ"),
            ("631985885", "R_kgDOJatW3Q"),  # preseeded
            ("623359086", "R_kgDOJSe0bg"),  # preseeded
        ]
        service_ids = [x[0] for x in repository_service_ids]
        service_ids_to_add = service_ids[:3]

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

        preseeded_repos = [
            repo_obj("631985885", "example-python", "python", False, "main", True),
            repo_obj("623359086", "sentry", "python", False, "main", True),
        ]

        for repo in preseeded_repos:
            new_repo = RepositoryFactory.create(
                private=repo["repo"]["private"],
                name=repo["repo"]["name"],
                using_integration=repo["_using_integration"],
                service_id=repo["repo"]["service_id"],
                owner=user,
            )
            dbsession.add(new_repo)
        dbsession.flush()

        # These are the repos we're supposed to query from the service provider
        async def side_effect(*args, **kwargs):
            results = [
                {
                    "branch": "main",
                    "language": "python",
                    "name": "codecov-cli",
                    "owner": {
                        "is_expected_owner": False,
                        "node_id": "MDEyOk9yZ2FuaXphdGlvbjgyMjYyMDU=",
                        "service_id": "8226205",
                        "username": "codecov",
                    },
                    "service_id": 460565350,
                    "private": False,
                },
                {
                    "branch": "main",
                    "language": "python",
                    "name": "worker",
                    "owner": {
                        "is_expected_owner": False,
                        "node_id": "MDEyOk9yZ2FuaXphdGlvbjgyMjYyMDU=",
                        "service_id": "8226205",
                        "username": "codecov",
                    },
                    "service_id": 665728948,
                    "private": False,
                },
                {
                    "branch": "main",
                    "language": "python",
                    "name": "components-demo",
                    "owner": {
                        "is_expected_owner": True,
                        "node_id": "U_kgDOBfIxWg",
                        "username": "giovanni-guidini",
                    },
                    "service_id": 553624697,
                    "private": False,
                },
            ]
            for r in results:
                yield r

        mock_owner_provider.get_repos_from_nodeids_generator.side_effect = side_effect
        mock_owner_provider.service = "github"

        SyncReposTask().run_impl(
            dbsession,
            ownerid=user.ownerid,
            using_integration=True,
            repository_service_ids=repository_service_ids,
        )
        dbsession.commit()

        mock_owner_provider.get_repos_from_nodeids_generator.assert_called_with(
            ["R_kgDOG3OrZg", "R_kgDOJ643tA", "R_kgDOIP-keQ"], user.username
        )

        repos = (
            dbsession.query(Repository)
            .filter(Repository.service_id.in_(service_ids))
            .all()
        )
        repos_added = list(
            filter(lambda repo: repo.service_id in service_ids_to_add, repos)
        )
        assert len(repos) == 5

        mocked_app.tasks[sync_repo_languages_gql_task_name].apply_async.calls(
            [
                call(
                    kwargs={
                        "current_owner_id": user.ownerid,
                        "org_username": user.ownerid,
                    }
                )
                for repo in repos_added
            ]
        )

        upserted_owner = (
            dbsession.query(Owner)
            .filter(Owner.service == "github", Owner.service_id == "8226205")
            .first()
        )
        assert upserted_owner is not None
        assert upserted_owner.username == "codecov"
