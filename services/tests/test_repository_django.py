import inspect
from datetime import UTC, datetime

import mock
import pytest
from asgiref.sync import async_to_sync
from freezegun import freeze_time
from shared.django_apps.codecov_auth.models import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Owner,
)
from shared.django_apps.core.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from shared.encryption.oauth import get_encryptor_from_configuration
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitServerUnreachableError,
)

from services.repository_django import (
    _is_repo_using_integration,
    _pick_best_base_comparedto_pair,
    fetch_and_update_pull_request_information,
    fetch_and_update_pull_request_information_from_commit,
    get_or_create_author,
    get_repo_provider_service,
)


@pytest.mark.parametrize("using_integration", [True, False])
def test__is_repo_using_integration_deprecated_flow(
    using_integration, transactional_db
):
    repo = RepositoryFactory.create(using_integration=using_integration)
    assert _is_repo_using_integration(repo) == using_integration


def test__is_repo_using_integration_ghapp_covers_all_repos(transactional_db):
    owner = OwnerFactory.create(service="github")
    repo = RepositoryFactory.create(author=owner)
    other_repo_same_owner = RepositoryFactory.create(author=owner)
    repo_different_owner = RepositoryFactory.create()
    assert repo.author != repo_different_owner.author
    ghapp_installation = GithubAppInstallation(
        name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        owner=owner,
        repository_service_ids=None,
        installation_id=12345,
    )
    ghapp_installation.save()

    assert _is_repo_using_integration(repo) == True
    assert _is_repo_using_integration(other_repo_same_owner) == True
    assert _is_repo_using_integration(repo_different_owner) == False


def test__is_repo_using_integration_ghapp_covers_some_repos(transactional_db):
    owner = OwnerFactory.create(service="github")
    repo = RepositoryFactory.create(author=owner)
    other_repo_same_owner = RepositoryFactory.create(author=owner)
    repo_different_owner = RepositoryFactory.create()
    assert repo.author != repo_different_owner.author
    ghapp_installation = GithubAppInstallation(
        name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        owner=owner,
        repository_service_ids=[repo.service_id],
        installation_id=12345,
    )
    ghapp_installation.save()
    assert _is_repo_using_integration(repo) == True
    assert _is_repo_using_integration(other_repo_same_owner) == False
    assert _is_repo_using_integration(repo_different_owner) == False


class TestRepositoryServiceTestCase(object):
    def test_get_repo_provider_service_github(self, transactional_db):
        repo = RepositoryFactory.create(
            author__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            author__service="github",
            name="example-python",
        )
        repo.save()
        res = async_to_sync(get_repo_provider_service)(repo)
        expected_data = {
            "owner": {
                "ownerid": repo.author.ownerid,
                "service_id": repo.author.service_id,
                "username": repo.author.username,
            },
            "repo": {
                "name": "example-python",
                "using_integration": False,
                "service_id": repo.service_id,
                "repoid": repo.repoid,
            },
            "installation": None,
            "fallback_installations": None,
        }
        assert res.data == expected_data
        assert repo.author.service == "github"
        assert res._on_token_refresh is not None
        assert inspect.isawaitable(res._on_token_refresh(None))
        assert res.token == {
            "username": repo.author.username,
            "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
            "secret": None,
        }

    def test_get_repo_provider_service_github_with_installations(
        self, transactional_db, mocker
    ):
        mocker.patch(
            "services.bots_django.github_apps.get_github_integration_token",
            return_value="installation_token",
        )
        mocker.patch(
            "shared.django_apps.codecov_auth.models.get_config", return_value=200
        )
        repo = RepositoryFactory.create(
            author__service="github",
            name="example-python",
            using_integration=False,
        )
        installation_0 = GithubAppInstallation(
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            installation_id=1200,
            app_id=200,
            repository_service_ids=None,
            owner=repo.author,
        )
        installation_1 = GithubAppInstallation(
            name="my_app",
            installation_id=1300,
            app_id=300,
            pem_path="path",
            repository_service_ids=None,
            owner=repo.author,
        )
        installation_0.save()
        installation_1.save()

        repo.author.github_app_installations.set([installation_0, installation_1])
        repo.save()

        res = async_to_sync(get_repo_provider_service)(
            repo, installation_name_to_use="my_app"
        )
        expected_data = {
            "owner": {
                "ownerid": repo.author.ownerid,
                "service_id": repo.author.service_id,
                "username": repo.author.username,
            },
            "repo": {
                "name": "example-python",
                "using_integration": True,
                "service_id": repo.service_id,
                "repoid": repo.repoid,
            },
            "installation": {
                "installation_id": 1300,
                "app_id": 300,
                "pem_path": "path",
            },
            "fallback_installations": [
                {"app_id": 200, "installation_id": 1200, "pem_path": None}
            ],
        }
        assert res.data == expected_data
        assert repo.author.service == "github"
        assert res._on_token_refresh is None
        assert res.token == {
            "key": "installation_token",
        }

    def test_get_repo_provider_service_bitbucket(self, transactional_db):
        repo = RepositoryFactory.create(
            author__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            author__service="bitbucket",
            name="example-python",
        )
        repo.save()
        res = async_to_sync(get_repo_provider_service)(repo)
        expected_data = {
            "owner": {
                "ownerid": repo.author.ownerid,
                "service_id": repo.author.service_id,
                "username": repo.author.username,
            },
            "repo": {
                "name": "example-python",
                "using_integration": False,
                "service_id": repo.service_id,
                "repoid": repo.repoid,
            },
            "installation": None,
            "fallback_installations": None,
        }
        assert res.data == expected_data
        assert repo.author.service == "bitbucket"
        assert res._on_token_refresh is None
        assert res.token == {
            "username": repo.author.username,
            "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
            "secret": None,
        }

    def test_get_repo_provider_service_with_token_refresh_callback(
        self, transactional_db
    ):
        repo = RepositoryFactory.create(
            author__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            author__service="gitlab",
            name="example-python",
        )
        repo.save()
        res = async_to_sync(get_repo_provider_service)(repo)
        expected_data = {
            "owner": {
                "ownerid": repo.author.ownerid,
                "service_id": repo.author.service_id,
                "username": repo.author.username,
            },
            "repo": {
                "name": "example-python",
                "using_integration": False,
                "service_id": repo.service_id,
                "repoid": repo.repoid,
            },
            "installation": None,
            "fallback_installations": None,
        }
        assert res.data == expected_data
        assert res._on_token_refresh is not None
        assert inspect.isawaitable(res._on_token_refresh(None))
        assert res.token == {
            "username": repo.author.username,
            "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
            "secret": None,
        }

    def test_get_repo_provider_service_repo_bot(
        self, transactional_db, mock_configuration
    ):
        repo = RepositoryFactory.create(
            author__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            author__service="gitlab",
            name="example-python",
            private=False,
        )

        res = async_to_sync(get_repo_provider_service)(repo)
        expected_data = {
            "owner": {
                "ownerid": repo.author.ownerid,
                "service_id": repo.author.service_id,
                "username": repo.author.username,
            },
            "repo": {
                "name": "example-python",
                "using_integration": False,
                "service_id": repo.service_id,
                "repoid": repo.repoid,
            },
            "installation": None,
            "fallback_installations": None,
        }
        assert res.data == expected_data
        assert res.token == {
            "username": repo.author.username,
            "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
            "secret": None,
        }
        assert res._on_token_refresh is not None

    def test_token_refresh_callback(self, transactional_db):
        repo = RepositoryFactory.create(
            author__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            author__service="gitlab",
            name="example-python",
        )
        repo.save()

        res = async_to_sync(get_repo_provider_service)(repo)
        new_token = dict(key="new_access_token", refresh_token="new_refresh_token")
        async_to_sync(res._on_token_refresh)(new_token)
        owner = Owner.objects.filter(ownerid=repo.author.ownerid).first()
        encryptor = get_encryptor_from_configuration()
        saved_token = encryptor.decrypt_token(owner.oauth_token)
        assert saved_token["key"] == "new_access_token"
        assert saved_token["refresh_token"] == "new_refresh_token"

    def test_get_repo_provider_service_different_bot(self, transactional_db):
        bot_token = "bcaa0dc0c66b4a8c8c65ac919a1a91aa"
        bot = OwnerFactory.create(unencrypted_oauth_token=bot_token)
        repo = RepositoryFactory.create(
            author__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            bot=bot,
            name="example-python",
        )
        repo.save()
        bot.save()

        res = async_to_sync(get_repo_provider_service)(repo)
        expected_data = {
            "owner": {
                "ownerid": repo.author.ownerid,
                "service_id": repo.author.service_id,
                "username": repo.author.username,
            },
            "repo": {
                "name": "example-python",
                "using_integration": False,
                "service_id": repo.service_id,
                "repoid": repo.repoid,
            },
            "installation": None,
            "fallback_installations": None,
        }
        assert res.data["repo"] == expected_data["repo"]
        assert res.data == expected_data
        assert res.token == {
            "username": repo.bot.username,
            "key": bot_token,
            "secret": None,
        }

    def test_get_repo_provider_service_no_bot(self, transactional_db):
        bot_token = "bcaa0dc0c66b4a8c8c65ac919a1a91aa"
        owner_bot = OwnerFactory.create(unencrypted_oauth_token=bot_token)
        repo = RepositoryFactory.create(
            author__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            author__bot=owner_bot,
            bot=None,
            name="example-python",
        )
        repo.save()
        owner_bot.save()

        res = async_to_sync(get_repo_provider_service)(repo)
        expected_data = {
            "owner": {
                "ownerid": repo.author.ownerid,
                "service_id": repo.author.service_id,
                "username": repo.author.username,
            },
            "repo": {
                "name": "example-python",
                "using_integration": False,
                "service_id": repo.service_id,
                "repoid": repo.repoid,
            },
            "installation": None,
            "fallback_installations": None,
        }
        assert res.data == expected_data
        assert res.token == {
            "username": repo.author.bot.username,
            "key": bot_token,
            "secret": None,
        }

    @freeze_time("2024-03-28T00:00:00")
    def test_get_or_create_author_doesnt_exist(self, transactional_db):
        service = "github"
        author_id = "123"
        username = "username"
        email = "email"
        name = "name"
        author = async_to_sync(get_or_create_author)(
            service, author_id, username, email, name
        )

        assert author.free == 0
        assert author is not None
        assert author.service == "github"
        assert author.service_id == "123"
        assert author.name == "name"
        assert author.email == "email"
        assert author.username == "username"
        assert author.plan_activated_users is None
        assert author.admins is None
        assert author.permission is None
        assert author.integration_id is None
        assert author.yaml is None
        assert author.oauth_token is None
        assert author.bot_id is None
        assert author.createstamp.isoformat() == "2024-03-28T00:00:00"

    def test_get_or_create_author_already_exists(self, transactional_db):
        owner = OwnerFactory.create(
            service="bitbucket",
            service_id="975",
            email="different_email@email.com",
            username="whoknew",
            yaml=dict(a=["12", "3"]),
        )

        owner.save()

        service = "bitbucket"
        author_id = "975"
        username = "username"
        email = "email"
        name = "name"
        author = async_to_sync(get_or_create_author)(
            service, author_id, username, email, name
        )

        assert author.ownerid == owner.ownerid
        assert author.free == 0
        assert author is not None
        assert author.service == "bitbucket"
        assert author.service_id == "975"
        assert author.name == owner.name
        assert author.email == "different_email@email.com"
        assert author.username == "whoknew"
        assert author.plan_activated_users == []
        assert author.admins == []
        assert author.permission == []
        assert author.integration_id is None
        assert author.yaml == {"a": ["12", "3"]}
        assert author.oauth_token == owner.oauth_token
        assert author.bot_id == owner.bot_id
        assert owner.createstamp is None


class TestPullRequestFetcher(object):
    def test_fetch_and_update_pull_request_information_from_commit_new_pull_commits_in_place(
        self, transactional_db, mocker
    ):
        now = datetime.now(UTC)
        commit = CommitFactory.create(
            message="",
            pullid=None,
            totals=None,
        )
        commit.timestamp = datetime.now()
        commit.pullid = 1
        base_commit = CommitFactory.create(repository=commit.repository, pullid=None)
        commit.save()

        base_commit.save()

        current_yaml = {}
        get_pull_request_result = {
            "base": {"branch": "master", "commitid": base_commit.commitid},
            "head": {"branch": "reason/some-testing", "commitid": commit.commitid},
            "number": "1",
            "id": "1",
            "state": "open",
            "title": "Creating new code for reasons no one knows",
            "author": {"id": "123", "username": "pr_author_username"},
        }
        repository_service = mocker.MagicMock(
            service="github",
            get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
        )

        enriched_pull = async_to_sync(
            fetch_and_update_pull_request_information_from_commit
        )(repository_service, commit, current_yaml)
        res = enriched_pull.database_pull

        assert res is not None
        assert res.repository_id == commit.repository_id
        assert res.pullid == 1
        assert res.issueid == 1
        assert res.updatestamp > now
        assert res.state == "open"
        assert res.title == "Creating new code for reasons no one knows"
        assert res.base == base_commit.commitid
        assert res.compared_to == base_commit.commitid
        assert res.head == commit.commitid
        assert res.commentid is None
        assert res.diff is None
        assert res._flare is None
        assert res._flare_storage_path is None
        assert (
            res.author
            == Owner.objects.filter(
                service="github",
                service_id=get_pull_request_result["author"]["id"],
                username=get_pull_request_result["author"]["username"],
            ).first()
        )

    def test_fetch_and_update_pull_request_information_from_commit_existing_pull_commits_in_place(
        self, transactional_db, mocker
    ):
        now = datetime.now(UTC)
        repository = RepositoryFactory.create()
        repository.save()

        pull = PullFactory.create(
            repository=repository, author=None, commentid=None, diff=None, pullid=1
        )
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            repository=repository,
        )
        base_commit = CommitFactory.create(repository=repository, branch="master")
        pull.save()
        commit.save()
        base_commit.save()

        current_yaml = {}
        f = {
            "author": {
                "id": "author_id",
                "username": "author_username",
                "email": "email@email.com",
                "name": "Mario",
            },
            "message": "Merged in aaaa/coverage.py (pull request #99) Fix #123: crash",
            "timestamp": datetime(2019, 10, 10),
            "parents": [],
        }
        get_pull_request_result = {
            "base": {"branch": "master", "commitid": base_commit.commitid},
            "head": {"branch": "reason/some-testing", "commitid": commit.commitid},
            "number": str(pull.pullid),
            "id": str(pull.pullid),
            "state": "open",
            "title": "Creating new code for reasons no one knows",
            "author": {"id": "123", "username": "pr_author_username"},
        }
        print("pullid", pull.pullid)
        repository_service = mocker.MagicMock(
            service="github",
            get_commit=mock.AsyncMock(return_value=f),
            get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
            find_pull_request=mock.AsyncMock(return_value=pull.pullid),
        )
        enriched_pull = async_to_sync(
            fetch_and_update_pull_request_information_from_commit
        )(repository_service, commit, current_yaml)
        res = enriched_pull.database_pull

        assert res is not None
        assert res == pull
        assert res.repository_id == commit.repository_id
        assert res.pullid == pull.pullid
        assert res.issueid == pull.pullid
        assert res.updatestamp > now
        assert res.state == "open"
        assert res.title == "Creating new code for reasons no one knows"
        assert res.base == base_commit.commitid
        assert res.compared_to == base_commit.commitid
        assert res.head == commit.commitid
        assert res.commentid is None
        assert res.diff is None
        assert res._flare is None
        assert res._flare_storage_path is None
        assert (
            res.author
            == Owner.objects.filter(
                service="github",
                service_id=get_pull_request_result["author"]["id"],
                username=get_pull_request_result["author"]["username"],
            ).first()
        )

    def test_fetch_and_update_pull_request_multiple_pulls_same_repo(
        self, transactional_db, mocker
    ):
        now = datetime.now(UTC)
        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(
            repository=repository,
            title="purposelly bad title",
            author=None,
            commentid=None,
            diff=None,
        )
        second_pull = PullFactory.create(repository=repository)
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            repository=repository,
        )
        base_commit = CommitFactory.create(repository=repository, branch="master")
        pull.save()
        second_pull.save()
        commit.save()
        base_commit.save()

        current_yaml = {}
        f = {
            "author": {
                "id": "author_id",
                "username": "author_username",
                "email": "email@email.com",
                "name": "Mario",
            },
            "message": "Merged in aaaa/coverage.py (pull request #99) Fix #123: crash",
            "timestamp": datetime(2019, 10, 10),
            "parents": [],
        }
        get_pull_request_result = {
            "base": {"branch": "master", "commitid": base_commit.commitid},
            "head": {"branch": "reason/some-testing", "commitid": commit.commitid},
            "number": str(pull.pullid),
            "id": str(pull.pullid),
            "state": "open",
            "title": "Creating new code for reasons no one knows",
            "author": {"id": "123", "username": "pr_author_username"},
        }

        repository_service = mocker.MagicMock(
            service="github",
            get_commit=mock.AsyncMock(return_value=f),
            get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
        )
        enriched_pull = async_to_sync(
            fetch_and_update_pull_request_information_from_commit
        )(repository_service, commit, current_yaml)
        res = enriched_pull.database_pull

        assert res is not None
        assert res == pull
        assert res != second_pull
        assert res.repository_id == commit.repository_id
        assert res.pullid == pull.pullid
        assert res.issueid == pull.pullid
        assert res.updatestamp > now
        assert res.state == "open"
        assert res.title == "Creating new code for reasons no one knows"
        assert res.base == base_commit.commitid
        assert res.compared_to == base_commit.commitid
        assert res.head == commit.commitid
        assert res.commentid is None
        assert res.diff is None
        assert res._flare is None
        assert res._flare_storage_path is None
        assert (
            res.author
            == Owner.objects.filter(
                service="github",
                service_id=get_pull_request_result["author"]["id"],
                username=get_pull_request_result["author"]["username"],
            ).first()
        )

    def test_fetch_and_update_pull_request_information_from_commit_different_compared_to(
        self, transactional_db, mocker
    ):
        now = datetime.now(UTC)
        repository = RepositoryFactory.create()
        repository.save()

        pull = PullFactory.create(
            repository=repository, author=None, commentid=None, diff=None
        )

        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            repository=repository,
        )
        second_comparedto_commit = CommitFactory.create(
            repository=repository,
            branch="master",
            merged=True,
            timestamp=datetime(2019, 5, 6),
        )
        compared_to_commit = CommitFactory.create(
            repository=repository,
            branch="master",
            merged=True,
            timestamp=datetime(2019, 7, 15),
        )
        pull.save()
        commit.save()
        second_comparedto_commit.save()
        compared_to_commit.save()
        current_yaml = {}
        f = {
            "author": {
                "id": "author_id",
                "username": "author_username",
                "email": "email@email.com",
                "name": "Mario",
            },
            "message": "Merged in aaaa/coverage.py (pull request #99) Fix #123: crash",
            "parents": [],
            "timestamp": datetime(2019, 10, 10),
        }
        get_pull_request_result = {
            "base": {"branch": "master", "commitid": "somecommitid"},
            "head": {"branch": "reason/some-testing", "commitid": commit.commitid},
            "number": str(pull.pullid),
            "id": str(pull.pullid),
            "state": "open",
            "title": "Creating new code for reasons no one knows",
            "author": {"id": "123", "username": "pr_author_username"},
        }
        repository_service = mocker.MagicMock(
            service="github",
            get_commit=mock.AsyncMock(return_value=f),
            get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
        )
        enriched_pull = async_to_sync(
            fetch_and_update_pull_request_information_from_commit
        )(repository_service, commit, current_yaml)
        res = enriched_pull.database_pull

        assert res is not None
        assert res == pull
        assert res.repository_id == commit.repository_id
        assert res.pullid == pull.pullid
        assert res.issueid == pull.pullid
        assert res.updatestamp > now
        assert res.state == "open"
        assert res.title == "Creating new code for reasons no one knows"
        assert res.base == "somecommitid"
        assert res.compared_to == compared_to_commit.commitid
        assert res.head == commit.commitid
        assert res.commentid is None
        assert res.diff is None
        assert res._flare is None
        assert res._flare_storage_path is None
        assert (
            res.author
            == Owner.objects.filter(
                service="github",
                service_id=get_pull_request_result["author"]["id"],
                username=get_pull_request_result["author"]["username"],
            ).first()
        )

    def test_fetch_and_update_pull_request_information_no_compared_to(
        self, transactional_db, mocker
    ):
        now = datetime.now()
        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(
            repository=repository,
            author=None,
            commentid=None,
            diff=None,
            head=None,
            base=None,
        )
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True, pullid=None
        )
        commit = CommitFactory.create(
            message="", totals=None, repository=repository, pullid=None
        )
        pull.save()
        commit.pullid = pull.pullid
        commit.save()
        compared_to_commit.save()

        current_yaml = {}
        get_pull_request_result = {
            "base": {"branch": "master", "commitid": "somecommitid"},
            "head": {"branch": "reason/some-testing", "commitid": commit.commitid},
            "number": str(pull.pullid),
            "id": str(pull.pullid),
            "state": "open",
            "title": "Creating new code for reasons no one knows",
            "author": {"id": "123", "username": "pr_author_username"},
        }
        repository_service = mocker.MagicMock(
            service="github",
            get_commit=mock.AsyncMock(
                side_effect=TorngitObjectNotFoundError("response", "message")
            ),
            get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
        )

        enriched_pull = async_to_sync(fetch_and_update_pull_request_information)(
            repository_service, pull.repository_id, pull.pullid, current_yaml
        )

        res = enriched_pull.database_pull

        res.refresh_from_db()

        assert res is not None
        assert res == pull
        assert res.repository_id == commit.repository_id
        assert res.pullid == pull.pullid
        assert res.issueid == pull.pullid
        assert res.updatestamp > now
        assert res.state == "open"
        assert res.title == "Creating new code for reasons no one knows"
        assert res.base == "somecommitid"
        assert res.compared_to is None
        assert res.head == commit.commitid
        assert res.commentid is None
        assert res.diff is None
        assert res._flare is None
        assert res._flare_storage_path is None
        assert (
            res.author
            == Owner.objects.filter(
                service="github",
                service_id=get_pull_request_result["author"]["id"],
                username=get_pull_request_result["author"]["username"],
            ).first()
        )

    def test_fetch_and_update_pull_request_information_torngitexception(
        self, transactional_db, mocker
    ):
        repository = RepositoryFactory.create()
        repository.save()
        commit = CommitFactory.create(
            message="",
            pullid=None,
            totals=None,
            repository=repository,
        )
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        commit.save()
        compared_to_commit.save()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            find_pull_request=mock.AsyncMock(
                side_effect=TorngitClientError(422, "response", "message")
            )
        )
        res = async_to_sync(fetch_and_update_pull_request_information_from_commit)(
            repository_service, commit, current_yaml
        )
        assert res is None

    def test_fetch_and_update_pull_request_information_torngitexception_getting_pull(
        self, transactional_db, mocker
    ):
        repository = RepositoryFactory.create()
        repository.save()
        commit = CommitFactory.create(
            message="",
            pullid=None,
            totals=None,
            repository=repository,
        )
        commit.timestamp = datetime.now()
        commit.pullid = "123"
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        commit.save()
        compared_to_commit.save()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(
                side_effect=TorngitObjectNotFoundError("response", "message")
            )
        )
        res = async_to_sync(fetch_and_update_pull_request_information_from_commit)(
            repository_service, commit, current_yaml
        )
        assert res.database_pull is None
        assert res.provider_pull is None

    def test_fetch_and_update_pull_request_information_torngitserverexception_getting_pull(
        self, transactional_db, mocker
    ):
        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(repository=repository)
        pull.save()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(side_effect=TorngitServerUnreachableError())
        )
        res = async_to_sync(fetch_and_update_pull_request_information)(
            repository_service, pull.repository_id, pull.pullid, current_yaml
        )
        assert res.database_pull == pull
        assert res.provider_pull is None

    def test_fetch_and_update_pull_request_information_notfound_pull_already_exists(
        self, transactional_db, mocker
    ):
        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(repository=repository)
        pull.save()
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            repository=repository,
        )
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        commit.save()
        compared_to_commit.save()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(
                side_effect=TorngitObjectNotFoundError("response", "message")
            )
        )
        res = async_to_sync(fetch_and_update_pull_request_information_from_commit)(
            repository_service, commit, current_yaml
        )
        assert res.database_pull == pull

    def test_pick_best_base_comparedto_pair_no_user_provided_base_no_candidate(
        self, mocker, transactional_db
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(repository=repository)
        pull.save()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = async_to_sync(_pick_best_base_comparedto_pair)(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == ("abcqwertabcqwertabcqwertabcqwertabcqwert", None)

    def test_pick_best_base_comparedto_pair_yes_user_provided_base_no_candidate(
        self, mocker, transactional_db
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(
            repository=repository,
            user_provided_base_sha="lkjhgfdslkjhgfdslkjhgfdslkjhgfdslkjhgfds",
        )
        pull.save()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = async_to_sync(_pick_best_base_comparedto_pair)(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == ("lkjhgfdslkjhgfdslkjhgfdslkjhgfdslkjhgfds", None)

    def test_pick_best_base_comparedto_pair_yes_user_provided_base_exact_match(
        self, mocker, transactional_db
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(
            repository=repository,
            user_provided_base_sha="1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )
        pull.save()
        commit = CommitFactory.create(
            repository=repository, commitid="1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        )
        commit.save()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = async_to_sync(_pick_best_base_comparedto_pair)(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )

    def test_pick_best_base_comparedto_pair_yes_user_given_no_base_exact_match(
        self, mocker, transactional_db
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(
            repository=repository,
            user_provided_base_sha="1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )
        pull.save()
        commit = CommitFactory.create(
            repository=repository, commitid="1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        )
        commit.save()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = async_to_sync(_pick_best_base_comparedto_pair)(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )

    def test_pick_best_base_comparedto_pair_yes_user_given_no_base_no_match(
        self, mocker, transactional_db
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(
            repository=repository,
            user_provided_base_sha="1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )
        pull.save()
        commit = CommitFactory.create(
            repository=repository,
            commitid="e9868516aafd365aeab2957d3745353b532d3a37",
            branch="basebranch",
            timestamp=datetime(2021, 3, 9),
            pullid=None,
        )
        other_commit = CommitFactory.create(
            repository=repository,
            commitid="2c07d7804dd9ff61ca5a1d6ee01de108af8cc7e0",
            branch="basebranch",
            timestamp=datetime(2021, 3, 11),
            pullid=None,
        )
        commit.save()
        other_commit.save()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = async_to_sync(_pick_best_base_comparedto_pair)(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
            "e9868516aafd365aeab2957d3745353b532d3a37",
        )

    def test_pick_best_base_comparedto_pair_yes_user_given_not_found(
        self, mocker, transactional_db
    ):
        async def get_commit_mocked(commit_sha):
            if commit_sha == "1007cbfb857592b9e7cbe3ecb25748870e2c07fc":
                raise TorngitObjectNotFoundError("response", "message")
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(
            repository=repository,
            user_provided_base_sha="1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )
        pull.save()
        commit = CommitFactory.create(
            repository=repository,
            commitid="e9868516aafd365aeab2957d3745353b532d3a37",
            branch="basebranch",
            timestamp=datetime(2021, 3, 9),
            pullid=None,
        )
        other_commit = CommitFactory.create(
            repository=repository,
            commitid="2c07d7804dd9ff61ca5a1d6ee01de108af8cc7e0",
            branch="basebranch",
            timestamp=datetime(2021, 3, 11),
            pullid=None,
        )
        commit.save()
        other_commit.save()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = async_to_sync(_pick_best_base_comparedto_pair)(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "abcqwertabcqwertabcqwertabcqwertabcqwert",
            "e9868516aafd365aeab2957d3745353b532d3a37",
        )

    def test_pick_best_base_comparedto_pair_no_user_given(
        self, mocker, transactional_db
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        repository = RepositoryFactory.create()
        repository.save()
        pull = PullFactory.create(repository=repository, user_provided_base_sha=None)
        pull.save()
        commit = CommitFactory.create(
            repository=repository,
            commitid="e9868516aafd365aeab2957d3745353b532d3a37",
            branch="basebranch",
            timestamp=datetime(2021, 3, 9),
            pullid=None,
        )
        other_commit = CommitFactory.create(
            repository=repository,
            commitid="2c07d7804dd9ff61ca5a1d6ee01de108af8cc7e0",
            branch="basebranch",
            timestamp=datetime(2021, 3, 11),
            pullid=None,
        )
        commit.save()
        other_commit.save()
        repository_service = mocker.MagicMock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = async_to_sync(_pick_best_base_comparedto_pair)(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "abcqwertabcqwertabcqwertabcqwertabcqwert",
            "e9868516aafd365aeab2957d3745353b532d3a37",
        )
