import inspect
from datetime import datetime
from unittest.mock import MagicMock, patch

import mock
import pytest
from freezegun import freeze_time
from shared.encryption.oauth import get_encryptor_from_configuration
from shared.rate_limits import gh_app_key_name, owner_key_name
from shared.reports.types import UploadType
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitServerUnreachableError,
)
from shared.typings.torngit import (
    AdditionalData,
    GithubInstallationInfo,
    OwnerInfo,
    RepoInfo,
    TorngitInstanceData,
)

from database.models import Owner
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Pull,
    Repository,
)
from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from services.repository import (
    _pick_best_base_comparedto_pair,
    fetch_and_update_pull_request_information,
    fetch_and_update_pull_request_information_from_commit,
    fetch_appropriate_parent_for_commit,
    fetch_commit_yaml_and_possibly_store,
    get_repo_provider_service,
    get_repo_provider_service_by_id,
    update_commit_from_provider_info,
    upsert_author,
)
from tasks.notify import get_repo_provider_service_for_specific_commit


@pytest.fixture
def repo(dbsession) -> Repository:
    repo = RepositoryFactory.create(
        owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
        owner__service="github",
        name="example-python",
    )
    dbsession.add(repo)
    dbsession.flush()
    return repo


@pytest.fixture
def pull(dbsession, repo) -> Pull:
    pull = PullFactory.create(repository=repo, author=None)
    dbsession.add(pull)
    dbsession.flush()
    return pull


def test_get_repo_provider_service_github(dbsession, repo):
    res = get_repo_provider_service(repo)
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": False,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {},
    }
    assert res.data == expected_data
    assert repo.owner.service == "github"
    assert res._on_token_refresh is not None
    assert inspect.isawaitable(res._on_token_refresh(None))
    assert res.token == {
        "username": repo.owner.username,
        "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
        "secret": None,
        "entity_name": owner_key_name(repo.owner.ownerid),
    }


def test_get_repo_provider_service_additional_data(dbsession, repo):
    additional_data: AdditionalData = {"upload_type": UploadType.TEST_RESULTS}
    res = get_repo_provider_service(repo, additional_data=additional_data)
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": False,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {"upload_type": UploadType.TEST_RESULTS},
    }
    assert res.data == expected_data
    assert repo.owner.service == "github"
    assert res._on_token_refresh is not None
    assert inspect.isawaitable(res._on_token_refresh(None))
    assert res.token == {
        "username": repo.owner.username,
        "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
        "secret": None,
        "entity_name": owner_key_name(repo.owner.ownerid),
    }


def test_get_repo_provider_service_github_with_installations(dbsession, mocker, repo):
    mocker.patch(
        "shared.bots.github_apps.get_github_integration_token",
        return_value="installation_token",
    )
    installation_0 = GithubAppInstallation(
        name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
        installation_id=1200,
        app_id=200,
        repository_service_ids=None,
        owner=repo.owner,
    )
    installation_1 = GithubAppInstallation(
        name="my_app",
        installation_id=1300,
        app_id=300,
        pem_path="path",
        repository_service_ids=None,
        owner=repo.owner,
    )
    repo.owner.github_app_installations = [installation_0, installation_1]
    dbsession.add_all([repo, installation_0, installation_1])
    dbsession.flush()
    res = get_repo_provider_service(repo, installation_name_to_use="my_app")
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": True,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": {
            "id": installation_1.id,
            "installation_id": 1300,
            "app_id": 300,
            "pem_path": "path",
        },
        "fallback_installations": [
            {
                "id": installation_0.id,
                "app_id": 200,
                "installation_id": 1200,
                "pem_path": None,
            }
        ],
        "additional_data": {},
    }
    assert res.data == expected_data
    assert repo.owner.service == "github"
    assert res._on_token_refresh is None
    assert res.token == {
        "key": "installation_token",
        "username": "installation_1300",
        "entity_name": gh_app_key_name(
            installation_id=installation_1.installation_id,
            app_id=installation_1.app_id,
        ),
    }


def test_get_repo_provider_service_bitbucket(dbsession):
    repo = RepositoryFactory.create(
        owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
        owner__service="bitbucket",
        name="example-python",
    )
    dbsession.add(repo)
    dbsession.flush()
    res = get_repo_provider_service(repo)
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": False,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {},
    }
    assert res.data == expected_data
    assert repo.owner.service == "bitbucket"
    assert res._on_token_refresh is None
    assert res.token == {
        "username": repo.owner.username,
        "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
        "secret": None,
        "entity_name": owner_key_name(repo.owner.ownerid),
    }


def test_get_repo_provider_service_with_token_refresh_callback(dbsession):
    repo = RepositoryFactory.create(
        owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
        owner__service="gitlab",
        name="example-python",
    )
    dbsession.add(repo)
    dbsession.flush()
    res = get_repo_provider_service(repo)
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": False,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {},
    }
    assert res.data == expected_data
    assert res._on_token_refresh is not None
    assert inspect.isawaitable(res._on_token_refresh(None))
    assert res.token == {
        "username": repo.owner.username,
        "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
        "secret": None,
        "entity_name": owner_key_name(repo.owner.ownerid),
    }


def test_get_repo_provider_service_repo_bot(dbsession, mock_configuration):
    repo = RepositoryFactory.create(
        owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
        owner__service="gitlab",
        name="example-python",
        private=False,
    )
    dbsession.add(repo)
    dbsession.flush()
    res = get_repo_provider_service(repo)
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": False,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {},
    }
    assert res.data == expected_data
    assert res.token == {
        "username": repo.owner.username,
        "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
        "secret": None,
        "entity_name": owner_key_name(repo.owner.ownerid),
    }
    assert res._on_token_refresh is not None


@pytest.mark.asyncio
async def test_token_refresh_callback(dbsession):
    repo = RepositoryFactory.create(
        owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
        owner__service="gitlab",
        name="example-python",
    )
    dbsession.add(repo)
    dbsession.flush()
    res = get_repo_provider_service(repo)
    new_token = dict(key="new_access_token", refresh_token="new_refresh_token")
    await res._on_token_refresh(new_token)
    owner = dbsession.query(Owner).filter_by(ownerid=repo.owner.ownerid).first()
    encryptor = get_encryptor_from_configuration()
    saved_token = encryptor.decrypt_token(owner.oauth_token)
    assert saved_token["key"] == "new_access_token"
    assert saved_token["refresh_token"] == "new_refresh_token"


def test_get_repo_provider_service_different_bot(dbsession):
    bot_token = "bcaa0dc0c66b4a8c8c65ac919a1a91aa"
    bot = OwnerFactory.create(unencrypted_oauth_token=bot_token)
    repo = RepositoryFactory.create(
        owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
        bot=bot,
        name="example-python",
    )
    dbsession.add(repo)
    dbsession.add(bot)
    dbsession.flush()
    res = get_repo_provider_service(repo)
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": False,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {},
    }
    assert res.data["repo"] == expected_data["repo"]
    assert res.data == expected_data
    assert res.token == {
        "username": repo.bot.username,
        "key": bot_token,
        "secret": None,
        "entity_name": owner_key_name(repo.bot.ownerid),
    }


def test_get_repo_provider_service_no_bot(dbsession):
    bot_token = "bcaa0dc0c66b4a8c8c65ac919a1a91aa"
    owner_bot = OwnerFactory.create(unencrypted_oauth_token=bot_token)
    repo = RepositoryFactory.create(
        owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
        owner__bot=owner_bot,
        bot=None,
        name="example-python",
    )
    dbsession.add(repo)
    dbsession.add(owner_bot)
    dbsession.flush()
    res = get_repo_provider_service(repo)
    expected_data = {
        "owner": {
            "ownerid": repo.owner.ownerid,
            "service_id": repo.owner.service_id,
            "username": repo.owner.username,
        },
        "repo": {
            "name": "example-python",
            "using_integration": False,
            "service_id": repo.service_id,
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {},
    }
    assert res.data == expected_data
    assert res.token == {
        "username": repo.owner.bot.username,
        "key": bot_token,
        "secret": None,
        "entity_name": owner_key_name(repo.owner.bot.ownerid),
    }


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_grandparent(
    dbsession, mock_repo_provider
):
    grandparent_commit_id = "8aa5aa054aaa21cf5a664acd504a1af6f5caafaa"
    parent_commit_id = "a" * 32
    repository = RepositoryFactory.create()
    parent_commit = CommitFactory.create(
        commitid=grandparent_commit_id, repository=repository
    )
    commit = CommitFactory.create(parent_commit_id=None, repository=repository)
    f = {
        "commitid": commit.commitid,
        "parents": [
            {
                "commitid": parent_commit_id,
                "parents": [{"commitid": grandparent_commit_id, "parents": []}],
            }
        ],
    }
    dbsession.add(parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id]}
    mock_repo_provider.get_ancestors_tree.return_value = f
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert grandparent_commit_id == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_parent_has_no_message(
    dbsession, mock_repo_provider
):
    grandparent_commit_id = "8aa5aa054aaa21cf5a664acd504a1af6f5caafaa"
    parent_commit_id = "a" * 32
    repository = RepositoryFactory.create()
    parent_with_no_message = CommitFactory.create(
        commitid=parent_commit_id,
        repository=repository,
        message=None,
        parent_commit_id=None,
    )
    parent_commit = CommitFactory.create(
        commitid=grandparent_commit_id, repository=repository
    )
    commit = CommitFactory.create(parent_commit_id=None, repository=repository)
    f = {
        "commitid": commit.commitid,
        "parents": [
            {
                "commitid": parent_commit_id,
                "parents": [{"commitid": grandparent_commit_id, "parents": []}],
            }
        ],
    }
    dbsession.add(parent_commit)
    dbsession.add(commit)
    dbsession.add(parent_with_no_message)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id]}
    mock_repo_provider.get_ancestors_tree.return_value = f
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert grandparent_commit_id == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_parent_is_deleted(
    dbsession, mock_repo_provider
):
    grandparent_commit_id = "8aa5aa054aaa21cf5a664acd504a1af6f5caafaa"
    parent_commit_id = "a" * 32
    repository = RepositoryFactory.create()
    parent_with_no_message = CommitFactory.create(
        commitid=parent_commit_id,
        repository=repository,
        message="message",
        parent_commit_id=None,
        deleted=True,
    )
    parent_commit = CommitFactory.create(
        commitid=grandparent_commit_id, repository=repository
    )
    commit = CommitFactory.create(parent_commit_id=None, repository=repository)
    f = {
        "commitid": commit.commitid,
        "parents": [
            {
                "commitid": parent_commit_id,
                "parents": [{"commitid": grandparent_commit_id, "parents": []}],
            }
        ],
    }
    dbsession.add(parent_commit)
    dbsession.add(commit)
    dbsession.add(parent_with_no_message)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id]}
    mock_repo_provider.get_ancestors_tree.return_value = f
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert grandparent_commit_id == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_parent_has_no_message_but_nothing_better(
    dbsession, mock_repo_provider
):
    grandparent_commit_id = "8aa5aa054aaa21cf5a664acd504a1af6f5caafaa"
    parent_commit_id = "a" * 32
    repository = RepositoryFactory.create()
    parent_with_no_message = CommitFactory.create(
        commitid=parent_commit_id,
        repository=repository,
        message=None,
        parent_commit_id=None,
    )
    commit = CommitFactory.create(parent_commit_id=None, repository=repository)
    f = {
        "commitid": commit.commitid,
        "parents": [
            {
                "commitid": parent_commit_id,
                "parents": [{"commitid": grandparent_commit_id, "parents": []}],
            }
        ],
    }
    dbsession.add(commit)
    dbsession.add(parent_with_no_message)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id]}
    mock_repo_provider.get_ancestors_tree.return_value = f
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert parent_commit_id == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_multiple_commit_parent_has_no_message_but_nothing_better(
    dbsession, mock_repo_provider
):
    grandparent_commit_id = "8aa5aa054aaa21cf5a664acd504a1af6f5caafaa"
    parent_commit_id = "a" * 32
    sec_parent_commit_id = "b" * 32
    repository = RepositoryFactory.create()
    parent_with_no_message = CommitFactory.create(
        commitid=parent_commit_id,
        repository=repository,
        message=None,
        parent_commit_id=None,
    )
    sec_parent_with_no_message = CommitFactory.create(
        commitid=sec_parent_commit_id,
        repository=repository,
        message=None,
        parent_commit_id=None,
        branch="bbb",
    )
    commit = CommitFactory.create(
        parent_commit_id=None, repository=repository, branch="bbb"
    )
    f = {
        "commitid": commit.commitid,
        "parents": [
            {
                "commitid": parent_commit_id,
                "parents": [{"commitid": grandparent_commit_id, "parents": []}],
            },
            {
                "commitid": sec_parent_commit_id,
                "parents": [{"commitid": grandparent_commit_id, "parents": []}],
            },
        ],
    }
    dbsession.add(commit)
    dbsession.add(parent_with_no_message)
    dbsession.add(sec_parent_with_no_message)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id, sec_parent_commit_id]}
    mock_repo_provider.get_ancestors_tree.return_value = f
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert sec_parent_commit_id == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_grandparent_wrong_repo_with_same(
    dbsession, mock_repo_provider
):
    grandparent_commit_id = "8aa5aa054aaa21cf5a664acd504a1af6f5caafaa"
    parent_commit_id = "39594a6cd3213e4a606de77486f16bbf22c4f42e"
    repository = RepositoryFactory.create()
    second_repository = RepositoryFactory.create()
    parent_commit = CommitFactory.create(
        commitid=grandparent_commit_id, repository=repository
    )
    commit = CommitFactory.create(parent_commit_id=None, repository=repository)
    deceiving_parent_commit = CommitFactory.create(
        commitid=parent_commit_id, repository=second_repository
    )
    f = {
        "commitid": commit.commitid,
        "parents": [
            {
                "commitid": parent_commit_id,
                "parents": [{"commitid": grandparent_commit_id, "parents": []}],
            }
        ],
    }
    dbsession.add(parent_commit)
    dbsession.add(commit)
    dbsession.add(deceiving_parent_commit)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id]}
    mock_repo_provider.get_ancestors_tree.return_value = f
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert grandparent_commit_id == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_grandparents_wrong_repo(
    dbsession, mock_repo_provider
):
    grandparent_commit_id = "8aa5aa054aaa21cf5a664acd504a1af6f5caafaa"
    parent_commit_id = "39594a6cd3213e4a606de77486f16bbf22c4f42e"
    second_parent_commit_id = "aaaaaa6cd3213e4a606de77486f16bbf22c4f422"
    repository = RepositoryFactory.create()
    second_repository = RepositoryFactory.create()
    parent_commit = CommitFactory.create(
        commitid=grandparent_commit_id, repository=repository, branch="aaa"
    )
    seconed_parent_commit = CommitFactory.create(
        commitid=second_parent_commit_id, repository=repository, branch="bbb"
    )
    commit = CommitFactory.create(
        parent_commit_id=None, repository=repository, branch="bbb"
    )
    deceiving_parent_commit = CommitFactory.create(
        commitid=parent_commit_id, repository=second_repository
    )
    f = {
        "commitid": commit.commitid,
        "parents": [
            {
                "commitid": parent_commit_id,
                "parents": [
                    {"commitid": grandparent_commit_id, "parents": []},
                    {"commitid": second_parent_commit_id, "parents": []},
                ],
            },
        ],
    }
    dbsession.add(seconed_parent_commit)
    dbsession.add(parent_commit)
    dbsession.add(commit)
    dbsession.add(deceiving_parent_commit)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id]}
    mock_repo_provider.get_ancestors_tree.return_value = f
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert second_parent_commit_id == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_direct_parent(
    dbsession, mock_repo_provider
):
    parent_commit_id = "8aa5be054aeb21cf5a664ecd504a1af6f5ceafba"
    repository = RepositoryFactory.create()
    parent_commit = CommitFactory.create(
        commitid=parent_commit_id, repository=repository
    )
    commit = CommitFactory.create(parent_commit_id=None, repository=repository)
    dbsession.add(parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    git_commit = {"parents": [parent_commit_id]}
    expected_result = parent_commit_id
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert expected_result == result


@pytest.mark.asyncio
async def test_fetch_appropriate_parent_for_commit_multiple_parents(
    dbsession, mock_repo_provider
):
    first_parent_commit_id = "8aa5be054aeb21cf5a664ecd504a1af6f5ceafba"
    second_parent_commit_id = "a" * 32
    repository = RepositoryFactory.create()
    second_parent_commit = CommitFactory.create(
        commitid=second_parent_commit_id, repository=repository, branch="2ndBranch"
    )
    first_parent_commit = CommitFactory.create(
        commitid=first_parent_commit_id, repository=repository, branch="1stBranch"
    )
    commit = CommitFactory.create(
        parent_commit_id=None, repository=repository, branch="1stBranch"
    )
    dbsession.add(second_parent_commit)
    dbsession.add(first_parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    git_commit = {"parents": [first_parent_commit_id, second_parent_commit_id]}
    expected_result = first_parent_commit_id
    result = await fetch_appropriate_parent_for_commit(
        mock_repo_provider, commit, git_commit
    )
    assert expected_result == result


@freeze_time("2024-03-28T00:00:00")
def test_upsert_author_doesnt_exist(dbsession):
    service = "github"
    author_id = "123"
    username = "username"
    email = "email"
    name = "name"
    author = upsert_author(dbsession, service, author_id, username, email, name)
    dbsession.flush()
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


def test_upsert_author_already_exists(dbsession):
    owner = OwnerFactory.create(
        service="bitbucket",
        service_id="975",
        email="different_email@email.com",
        username="whoknew",
        yaml=dict(a=["12", "3"]),
    )
    dbsession.add(owner)
    dbsession.flush()
    service = "bitbucket"
    author_id = "975"
    username = "username"
    email = "email"
    name = "name"
    author = upsert_author(dbsession, service, author_id, username, email, name)
    dbsession.flush()
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


def test_upsert_author_needs_update(dbsession):
    username = "username"
    email = "email@email.com"
    service = "bitbucket"
    service_id = "975"
    owner = OwnerFactory.create(
        service=service,
        service_id=service_id,
        email=email,
        username=username,
        yaml=dict(a=["12", "3"]),
    )
    dbsession.add(owner)
    dbsession.flush()

    new_name = "Newt Namenheim"
    new_username = "new_username"
    new_email = "new_email@email.com"
    author = upsert_author(
        dbsession, service, service_id, new_username, new_email, new_name
    )
    dbsession.flush()

    assert author is not None
    assert author.ownerid == owner.ownerid
    assert author.free == 0
    assert author.service == service
    assert author.service_id == service_id
    assert author.name == new_name
    assert author.email == new_email
    assert author.username == new_username
    assert author.plan_activated_users == []
    assert author.admins == []
    assert author.permission == []
    assert author.integration_id is None
    assert author.yaml == {"a": ["12", "3"]}
    assert author.oauth_token == owner.oauth_token
    assert author.bot_id == owner.bot_id


@pytest.mark.asyncio
async def test_update_commit_from_provider_info_no_author_id(dbsession, mocker):
    possible_parent_commit = CommitFactory.create(
        message="possible_parent_commit", pullid=None
    )
    commit = CommitFactory.create(
        message="",
        author=None,
        pullid=1,
        totals=None,
        _report_json=None,
        repository=possible_parent_commit.repository,
    )
    dbsession.add(possible_parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    dbsession.refresh(commit)
    f = {
        "author": {
            "id": None,
            "username": None,
            "email": "email@email.com",
            "name": "Mario",
        },
        "message": "This message is brought to you by",
        "parents": [possible_parent_commit.commitid],
        "timestamp": "2018-07-09T23:39:20Z",
    }
    get_pull_request_result = {
        "head": {"branch": "newbranchyeah"},
        "base": {"branch": "main"},
    }
    repository_service = mocker.MagicMock(
        get_commit=mock.AsyncMock(return_value=f),
        get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
    )
    await update_commit_from_provider_info(repository_service, commit)
    dbsession.flush()
    dbsession.refresh(commit)
    assert commit.author is None
    assert commit.message == "This message is brought to you by"
    assert commit.pullid == 1
    assert commit.totals is None
    assert commit.report_json == {}
    assert commit.branch == "newbranchyeah"
    assert commit.merged is False
    assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
    assert commit.parent_commit_id == possible_parent_commit.commitid
    assert commit.state == "complete"


@pytest.mark.asyncio
async def test_update_commit_from_provider_info_no_pullid_on_defaultbranch(
    dbsession, mocker, mock_repo_provider
):
    repository = RepositoryFactory.create(branch="superbranch")
    dbsession.add(repository)
    dbsession.flush()
    possible_parent_commit = CommitFactory.create(
        message="possible_parent_commit", pullid=None, repository=repository
    )
    commit = CommitFactory.create(
        message="",
        author=None,
        pullid=None,
        totals=None,
        branch="papapa",
        _report_json=None,
        repository=repository,
    )
    dbsession.add(possible_parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    dbsession.refresh(commit)
    mock_repo_provider.find_pull_request.return_value = None
    mock_repo_provider.get_best_effort_branches.return_value = [
        "superbranch",
        "else",
        "pokemon",
    ]
    mock_repo_provider.get_commit.return_value = {
        "author": {
            "id": None,
            "username": None,
            "email": "email@email.com",
            "name": "Mario",
        },
        "message": "This message is brought to you by",
        "parents": [possible_parent_commit.commitid],
        "timestamp": "2018-07-09T23:39:20Z",
    }
    await update_commit_from_provider_info(mock_repo_provider, commit)
    dbsession.flush()
    dbsession.refresh(commit)
    assert commit.author is None
    assert commit.message == "This message is brought to you by"
    assert commit.pullid is None
    assert commit.totals is None
    assert commit.report_json == {}
    assert commit.branch == "superbranch"
    assert commit.merged is True
    assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
    assert commit.parent_commit_id == possible_parent_commit.commitid
    assert commit.state == "complete"


@pytest.mark.asyncio
async def test_update_commit_from_provider_info_no_pullid_not_on_defaultbranch(
    dbsession, mocker, mock_repo_provider
):
    repository = RepositoryFactory.create(branch="superbranch")
    dbsession.add(repository)
    dbsession.flush()
    possible_parent_commit = CommitFactory.create(
        message="possible_parent_commit", pullid=None, repository=repository
    )
    commit = CommitFactory.create(
        message="",
        author=None,
        pullid=None,
        branch="papapa",
        totals=None,
        _report_json=None,
        repository=repository,
    )
    dbsession.add(possible_parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    dbsession.refresh(commit)
    mock_repo_provider.find_pull_request.return_value = None
    mock_repo_provider.get_best_effort_branches.return_value = ["else", "pokemon"]
    mock_repo_provider.get_commit.return_value = {
        "author": {
            "id": None,
            "username": None,
            "email": "email@email.com",
            "name": "Mario",
        },
        "message": "This message is brought to you by",
        "parents": [possible_parent_commit.commitid],
        "timestamp": "2018-07-09T23:39:20Z",
    }
    await update_commit_from_provider_info(mock_repo_provider, commit)
    dbsession.flush()
    dbsession.refresh(commit)
    assert commit.author is None
    assert commit.message == "This message is brought to you by"
    assert commit.pullid is None
    assert commit.totals is None
    assert commit.report_json == {}
    assert commit.branch == "papapa"
    assert commit.merged is False
    assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
    assert commit.parent_commit_id == possible_parent_commit.commitid
    assert commit.state == "complete"


@pytest.mark.asyncio
async def test_update_commit_from_provider_info_with_author_id(dbsession, mocker):
    possible_parent_commit = CommitFactory.create(
        message="possible_parent_commit", pullid=None
    )
    commit = CommitFactory.create(
        message="",
        author=None,
        pullid=1,
        totals=None,
        _report_json=None,
        repository=possible_parent_commit.repository,
    )
    dbsession.add(possible_parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    dbsession.refresh(commit)
    f = {
        "author": {
            "id": "author_id",
            "username": "author_username",
            "email": "email@email.com",
            "name": "Mario",
        },
        "message": "This message is brought to you by",
        "parents": [possible_parent_commit.commitid],
        "timestamp": "2018-07-09T23:39:20Z",
    }
    get_pull_request_result = {
        "head": {"branch": "newbranchyeah"},
        "base": {"branch": "main"},
    }
    repository_service = mocker.MagicMock(
        get_commit=mock.AsyncMock(return_value=f),
        get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
    )
    await update_commit_from_provider_info(repository_service, commit)
    dbsession.flush()
    dbsession.refresh(commit)
    assert commit.message == "This message is brought to you by"
    assert commit.pullid == 1
    assert commit.totals is None
    assert commit.report_json == {}
    assert commit.branch == "newbranchyeah"
    assert commit.parent_commit_id == possible_parent_commit.commitid
    assert commit.state == "complete"
    assert commit.author is not None
    assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
    assert commit.author.username == "author_username"


@pytest.mark.asyncio
async def test_update_commit_from_provider_info_pull_from_fork(dbsession, mocker):
    possible_parent_commit = CommitFactory.create(
        message="possible_parent_commit", pullid=None
    )
    commit = CommitFactory.create(
        message="",
        author=None,
        pullid=1,
        totals=None,
        _report_json=None,
        repository=possible_parent_commit.repository,
    )
    dbsession.add(possible_parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    dbsession.refresh(commit)
    f = {
        "author": {
            "id": "author_id",
            "username": "author_username",
            "email": "email@email.com",
            "name": "Mario",
        },
        "message": "This message is brought to you by",
        "parents": [possible_parent_commit.commitid],
        "timestamp": "2018-07-09T23:39:20Z",
    }
    get_pull_request_result = {
        "head": {"branch": "main", "slug": f"some-guy/{commit.repository.name}"},
        "base": {
            "branch": "main",
            "slug": f"{commit.repository.owner.username}/{commit.repository.name}",
        },
    }
    repository_service = mocker.MagicMock(
        get_commit=mock.AsyncMock(return_value=f),
        get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
    )
    await update_commit_from_provider_info(repository_service, commit)
    dbsession.flush()
    dbsession.refresh(commit)
    assert commit.message == "This message is brought to you by"
    assert commit.pullid == 1
    assert commit.totals is None
    assert commit.report_json == {}
    assert commit.branch == f"some-guy/{commit.repository.name}:main"
    assert commit.parent_commit_id == possible_parent_commit.commitid
    assert commit.state == "complete"
    assert commit.author is not None
    assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
    assert commit.author.username == "author_username"


@pytest.mark.asyncio
async def test_update_commit_from_provider_info_bitbucket_merge(dbsession, mocker):
    possible_parent_commit = CommitFactory.create(
        message="possible_parent_commit",
        pullid=None,
        repository__owner__service="bitbucket",
    )
    commit = CommitFactory.create(
        message="",
        author=None,
        pullid=1,
        totals=None,
        _report_json=None,
        repository=possible_parent_commit.repository,
    )
    dbsession.add(possible_parent_commit)
    dbsession.add(commit)
    dbsession.flush()
    dbsession.refresh(commit)
    f = {
        "author": {
            "id": "author_id",
            "username": "author_username",
            "email": "email@email.com",
            "name": "Mario",
        },
        "message": "Merged in aaaa/coverage.py (pull request #99) Fix #123: crash",
        "parents": [possible_parent_commit.commitid],
        "timestamp": "2018-07-09T23:39:20Z",
    }
    get_pull_request_result = {
        "head": {"branch": "newbranchyeah"},
        "base": {"branch": "thebasebranch"},
    }
    repository_service = mocker.MagicMock(
        get_commit=mock.AsyncMock(return_value=f),
        get_pull_request=mock.AsyncMock(return_value=get_pull_request_result),
    )
    await update_commit_from_provider_info(repository_service, commit)
    dbsession.flush()
    dbsession.refresh(commit)
    assert (
        commit.message
        == "Merged in aaaa/coverage.py (pull request #99) Fix #123: crash"
    )
    assert commit.pullid == 1
    assert commit.totals is None
    assert commit.report_json == {}
    assert commit.branch == "thebasebranch"
    assert commit.parent_commit_id == possible_parent_commit.commitid
    assert commit.state == "complete"
    assert commit.author is not None
    assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
    assert commit.author.username == "author_username"


@pytest.mark.asyncio
async def test_get_repo_gh_no_integration(dbsession, mocker):
    owner = OwnerFactory.create(
        service="github",
        username="1nf1n1t3l00p",
        service_id="45343385",
        unencrypted_oauth_token="bcaa0dc0c66b4a8c8c65ac919a1a91aa",
    )
    dbsession.add(owner)

    repo = RepositoryFactory.create(
        private=True,
        name="pytest",
        using_integration=False,
        service_id="123456",
        owner=owner,
    )
    dbsession.add(repo)
    dbsession.flush()

    res = get_repo_provider_service_by_id(dbsession, repo.repoid)

    expected_data = {
        "owner": {
            "ownerid": owner.ownerid,
            "service_id": owner.service_id,
            "username": owner.username,
        },
        "repo": {
            "name": "pytest",
            "using_integration": False,
            "service_id": "123456",
            "repoid": repo.repoid,
        },
        "installation": None,
        "fallback_installations": None,
        "additional_data": {},
    }
    assert res.data["repo"] == expected_data["repo"]
    assert res.data == expected_data
    assert res.token == {
        "username": "1nf1n1t3l00p",
        "key": "bcaa0dc0c66b4a8c8c65ac919a1a91aa",
        "secret": None,
        "entity_name": owner_key_name(repo.owner.ownerid),
    }


class TestGetRepoProviderServiceForSpecificCommit(object):
    @pytest.fixture
    def mock_get_repo_provider_service(self, mocker):
        mock_get_repo_provider_service = mocker.patch(
            "tasks.notify.get_repo_provider_service"
        )
        return mock_get_repo_provider_service

    @pytest.fixture
    def mock_redis(self, mocker):
        fake_redis = MagicMock(name="fake_redis")
        mock_conn = mocker.patch("services.github.get_redis_connection")
        mock_conn.return_value = fake_redis
        return fake_redis

    def test_get_repo_provider_service_for_specific_commit_not_gh(
        self, dbsession, mock_get_repo_provider_service, mock_redis
    ):
        commit = CommitFactory(repository__owner__service="gitlab")
        mock_get_repo_provider_service.return_value = "the TorngitAdapter"
        response = get_repo_provider_service_for_specific_commit(commit, "some_name")
        assert response == "the TorngitAdapter"
        mock_get_repo_provider_service.assert_called_with(
            commit.repository, "some_name"
        )

    @patch("tasks.notify._possibly_pin_commit_to_github_app")
    def test_get_repo_provider_service_for_specific_commit_no_specific_app_for_commit(
        self, mock_pin, dbsession, mock_get_repo_provider_service, mock_redis
    ):
        commit = CommitFactory(repository__owner__service="github")
        assert commit.id not in [10000, 15000]
        redis_keys = {
            "app_to_use_for_commit_15000": b"1200",
            "app_to_use_for_commit_10000": b"1000",
        }
        mock_redis.get.side_effect = lambda key: redis_keys.get(key)

        mock_get_repo_provider_service.return_value = "the TorngitAdapter"

        response = get_repo_provider_service_for_specific_commit(commit, "some_name")
        assert response == "the TorngitAdapter"
        mock_get_repo_provider_service.assert_called_with(
            commit.repository, "some_name"
        )

    @patch("tasks.notify.get_github_app_token", return_value=("the app token", None))
    @patch(
        "tasks.notify._get_repo_provider_service_instance",
        return_value="the TorngitAdapter",
    )
    def test_get_repo_provider_service_for_specific_commit(
        self,
        mock_get_instance,
        mock_get_app_token,
        dbsession,
        mock_get_repo_provider_service,
        mock_redis,
    ):
        commit = CommitFactory(repository__owner__service="github")
        app = GithubAppInstallation(
            owner=commit.repository.owner, app_id=12, installation_id=1200
        )
        dbsession.add_all([commit, app])
        dbsession.flush()
        assert commit.repository.owner.github_app_installations == [app]
        redis_keys = {
            f"app_to_use_for_commit_{commit.id}": str(app.id).encode(),
        }
        mock_redis.get.side_effect = lambda key: redis_keys.get(key)
        response = get_repo_provider_service_for_specific_commit(commit, "some_name")
        assert response == "the TorngitAdapter"
        mock_get_instance.assert_called_once()

        data = TorngitInstanceData(
            repo=RepoInfo(
                name=commit.repository.name,
                using_integration=True,
                service_id=commit.repository.service_id,
                repoid=commit.repository.repoid,
            ),
            owner=OwnerInfo(
                service_id=commit.repository.owner.service_id,
                ownerid=commit.repository.ownerid,
                username=commit.repository.owner.username,
            ),
            installation=GithubInstallationInfo(
                id=app.id, app_id=12, installation_id=1200, pem_path=None
            ),
            fallback_installations=None,
        )
        mock_get_instance.assert_called_with(
            "github",
            dict(
                **data,
                token="the app token",
                token_type_mapping=None,
                on_token_refresh=None,
            ),
        )

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_from_commit_new_pull_commits_in_place(
        self, dbsession, mocker
    ):
        now = datetime.utcnow()
        commit = CommitFactory.create(message="", totals=None, _report_json=None)
        base_commit = CommitFactory.create(repository=commit.repository)
        dbsession.add(commit)
        dbsession.add(base_commit)
        dbsession.flush()
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

        # Setting the pullid for the commit without flushing. This ensures that we don't try to build the pull object,
        # so that it can go through the path that creates/updates the pull object from `get_pull_request_result`
        commit.pullid = 1
        enriched_pull = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        res = enriched_pull.database_pull
        dbsession.flush()
        dbsession.refresh(res)
        assert res is not None
        assert res.repoid == commit.repoid
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
            == dbsession.query(Owner)
            .filter(
                Owner.service == "github",
                Owner.service_id == get_pull_request_result["author"]["id"],
                Owner.username == get_pull_request_result["author"]["username"],
            )
            .first()
        )

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_from_commit_existing_pull_commits_in_place(
        self, dbsession, mocker, repo, pull
    ):
        now = datetime.utcnow()
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            _report_json=None,
            repository=repo,
        )
        base_commit = CommitFactory.create(repository=repo, branch="master")
        dbsession.add(pull)
        dbsession.add(commit)
        dbsession.add(base_commit)
        dbsession.flush()
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
        enriched_pull = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        res = enriched_pull.database_pull
        dbsession.flush()
        dbsession.refresh(res)
        assert res is not None
        assert res == pull
        assert res.repoid == commit.repoid
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
            == dbsession.query(Owner)
            .filter(
                Owner.service == "github",
                Owner.service_id == get_pull_request_result["author"]["id"],
                Owner.username == get_pull_request_result["author"]["username"],
            )
            .first()
        )

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_multiple_pulls_same_repo(
        self, dbsession, mocker, repo, pull
    ):
        now = datetime.utcnow()
        pull.title = "purposelly bad title"
        second_pull = PullFactory.create(repository=repo)
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            _report_json=None,
            repository=repo,
        )
        base_commit = CommitFactory.create(repository=repo, branch="master")
        dbsession.add(pull)
        dbsession.add(second_pull)
        dbsession.add(commit)
        dbsession.add(base_commit)
        dbsession.flush()
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
        enriched_pull = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        res = enriched_pull.database_pull
        dbsession.flush()
        dbsession.refresh(res)
        assert res is not None
        assert res == pull
        assert res != second_pull
        assert res.repoid == commit.repoid
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
            == dbsession.query(Owner)
            .filter(
                Owner.service == "github",
                Owner.service_id == get_pull_request_result["author"]["id"],
                Owner.username == get_pull_request_result["author"]["username"],
            )
            .first()
        )

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_from_commit_different_compared_to(
        self,
        dbsession,
        mocker,
        repo,
        pull,
    ):
        now = datetime.utcnow()
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            _report_json=None,
            repository=repo,
        )
        second_comparedto_commit = CommitFactory.create(
            repository=repo,
            branch="master",
            merged=True,
            timestamp=datetime(2019, 5, 6),
        )
        compared_to_commit = CommitFactory.create(
            repository=repo,
            branch="master",
            merged=True,
            timestamp=datetime(2019, 7, 15),
        )
        dbsession.add(commit)
        dbsession.add(second_comparedto_commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()
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
        enriched_pull = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        res = enriched_pull.database_pull
        dbsession.flush()
        dbsession.refresh(res)
        assert res is not None
        assert res == pull
        assert res.repoid == commit.repoid
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
            == dbsession.query(Owner)
            .filter(
                Owner.service == "github",
                Owner.service_id == get_pull_request_result["author"]["id"],
                Owner.username == get_pull_request_result["author"]["username"],
            )
            .first()
        )

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_no_compared_to(
        self, dbsession, mocker, repo, pull
    ):
        now = datetime.utcnow()
        compared_to_commit = CommitFactory.create(
            repository=repo, branch="master", merged=True
        )
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            _report_json=None,
            repository=repo,
        )
        dbsession.add(pull)
        dbsession.add(commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()
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
        enriched_pull = await fetch_and_update_pull_request_information(
            repository_service, dbsession, pull.repoid, pull.pullid, current_yaml
        )
        res = enriched_pull.database_pull
        dbsession.flush()
        dbsession.refresh(res)
        assert res is not None
        assert res == pull
        assert res.repoid == commit.repoid
        assert res.pullid == pull.pullid
        assert res.issueid == pull.pullid
        assert res.updatestamp > now
        assert res.state == "open"
        assert res.title == "Creating new code for reasons no one knows"
        assert res.base == "somecommitid"
        assert res.compared_to is None
        assert res.head is None
        assert res.commentid is None
        assert res.diff is None
        assert res._flare is None
        assert res._flare_storage_path is None
        assert (
            res.author
            == dbsession.query(Owner)
            .filter(
                Owner.service == "github",
                Owner.service_id == get_pull_request_result["author"]["id"],
                Owner.username == get_pull_request_result["author"]["username"],
            )
            .first()
        )

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_torngitexception(
        self, dbsession, mocker, repo
    ):
        commit = CommitFactory.create(
            message="",
            pullid=None,
            totals=None,
            _report_json=None,
            repository=repo,
        )
        compared_to_commit = CommitFactory.create(
            repository=repo, branch="master", merged=True
        )
        dbsession.add(commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            find_pull_request=mock.AsyncMock(
                side_effect=TorngitClientError(422, "response", "message")
            )
        )
        res = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        assert res is None

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_torngitexception_getting_pull(
        self, dbsession, mocker, repo
    ):
        commit = CommitFactory.create(
            message="",
            totals=None,
            _report_json=None,
            repository=repo,
        )
        compared_to_commit = CommitFactory.create(
            repository=repo, branch="master", merged=True
        )
        dbsession.add(commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()

        commit.pullid = "123"
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(
                side_effect=TorngitObjectNotFoundError("response", "message")
            )
        )
        res = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        assert res.database_pull is None
        assert res.provider_pull is None

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_torngitserverexception_getting_pull(
        self, dbsession, mocker, repo, pull
    ):
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(side_effect=TorngitServerUnreachableError())
        )
        res = await fetch_and_update_pull_request_information(
            repository_service, dbsession, pull.repoid, pull.pullid, current_yaml
        )
        assert res.database_pull == pull
        assert res.provider_pull is None

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_notfound_pull_already_exists(
        self, dbsession, mocker, repo, pull
    ):
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            _report_json=None,
            repository=repo,
        )
        compared_to_commit = CommitFactory.create(
            repository=repo, branch="master", merged=True
        )
        dbsession.add(commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(
                side_effect=TorngitObjectNotFoundError("response", "message")
            )
        )
        res = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        assert res.database_pull == pull

    @pytest.mark.asyncio
    async def test_pick_best_base_comparedto_pair_no_user_provided_base_no_candidate(
        self, mocker, dbsession, repo, pull
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        dbsession.flush()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = await _pick_best_base_comparedto_pair(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == ("abcqwertabcqwertabcqwertabcqwertabcqwert", None)

    @pytest.mark.asyncio
    async def test_pick_best_base_comparedto_pair_yes_user_provided_base_no_candidate(
        self, mocker, dbsession, repo, pull
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        pull.user_provided_base_sha = "lkjhgfdslkjhgfdslkjhgfdslkjhgfdslkjhgfds"
        dbsession.add(pull)
        dbsession.flush()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = await _pick_best_base_comparedto_pair(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == ("lkjhgfdslkjhgfdslkjhgfdslkjhgfdslkjhgfds", None)

    @pytest.mark.asyncio
    async def test_pick_best_base_comparedto_pair_yes_user_provided_base_exact_match(
        self, mocker, dbsession, repo, pull
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        pull.user_provided_base_sha = "1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        dbsession.add(pull)
        dbsession.flush()
        commit = CommitFactory.create(
            repository=repo, commitid="1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        )
        dbsession.add(commit)
        dbsession.flush()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = await _pick_best_base_comparedto_pair(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )

    @pytest.mark.asyncio
    async def test_pick_best_base_comparedto_pair_yes_user_given_no_base_exact_match(
        self, mocker, dbsession, repo, pull
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        pull.user_provided_base_sha = "1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        dbsession.add(pull)
        dbsession.flush()
        commit = CommitFactory.create(
            repository=repo, commitid="1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        )
        dbsession.add(commit)
        dbsession.flush()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = await _pick_best_base_comparedto_pair(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
        )

    @pytest.mark.asyncio
    async def test_pick_best_base_comparedto_pair_yes_user_given_no_base_no_match(
        self, mocker, dbsession, repo, pull
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        pull.user_provided_base_sha = "1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        dbsession.add(pull)
        dbsession.flush()
        commit = CommitFactory.create(
            repository=repo,
            commitid="e9868516aafd365aeab2957d3745353b532d3a37",
            branch="basebranch",
            timestamp=datetime(2021, 3, 9),
            pullid=None,
        )
        other_commit = CommitFactory.create(
            repository=repo,
            commitid="2c07d7804dd9ff61ca5a1d6ee01de108af8cc7e0",
            branch="basebranch",
            timestamp=datetime(2021, 3, 11),
            pullid=None,
        )
        dbsession.add(commit)
        dbsession.add(other_commit)
        dbsession.flush()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = await _pick_best_base_comparedto_pair(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "1007cbfb857592b9e7cbe3ecb25748870e2c07fc",
            "e9868516aafd365aeab2957d3745353b532d3a37",
        )

    @pytest.mark.asyncio
    async def test_pick_best_base_comparedto_pair_yes_user_given_not_found(
        self,
        mocker,
        dbsession,
        repo,
        pull,
    ):
        async def get_commit_mocked(commit_sha):
            if commit_sha == "1007cbfb857592b9e7cbe3ecb25748870e2c07fc":
                raise TorngitObjectNotFoundError("response", "message")
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        pull.user_provided_base_sha = "1007cbfb857592b9e7cbe3ecb25748870e2c07fc"
        dbsession.add(pull)
        dbsession.flush()
        commit = CommitFactory.create(
            repository=repo,
            commitid="e9868516aafd365aeab2957d3745353b532d3a37",
            branch="basebranch",
            timestamp=datetime(2021, 3, 9),
            pullid=None,
        )
        other_commit = CommitFactory.create(
            repository=repo,
            commitid="2c07d7804dd9ff61ca5a1d6ee01de108af8cc7e0",
            branch="basebranch",
            timestamp=datetime(2021, 3, 11),
            pullid=None,
        )
        dbsession.add(commit)
        dbsession.add(other_commit)
        dbsession.flush()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = await _pick_best_base_comparedto_pair(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "abcqwertabcqwertabcqwertabcqwertabcqwert",
            "e9868516aafd365aeab2957d3745353b532d3a37",
        )

    @pytest.mark.asyncio
    async def test_pick_best_base_comparedto_pair_no_user_given(
        self, mocker, dbsession, repo, pull
    ):
        async def get_commit_mocked(commit_sha):
            return {"timestamp": datetime(2021, 3, 10).isoformat()}

        commit = CommitFactory.create(
            repository=repo,
            commitid="e9868516aafd365aeab2957d3745353b532d3a37",
            branch="basebranch",
            timestamp=datetime(2021, 3, 9),
            pullid=None,
        )
        other_commit = CommitFactory.create(
            repository=repo,
            commitid="2c07d7804dd9ff61ca5a1d6ee01de108af8cc7e0",
            branch="basebranch",
            timestamp=datetime(2021, 3, 11),
            pullid=None,
        )
        dbsession.add(commit)
        dbsession.add(other_commit)
        dbsession.flush()
        repository_service = mocker.Mock(
            TorngitBaseAdapter, get_commit=get_commit_mocked
        )
        current_yaml = mocker.MagicMock()
        pull_information = {
            "base": {"commitid": "abcqwert" * 5, "branch": "basebranch"}
        }
        res = await _pick_best_base_comparedto_pair(
            repository_service, pull, current_yaml, pull_information
        )
        assert res == (
            "abcqwertabcqwertabcqwertabcqwertabcqwert",
            "e9868516aafd365aeab2957d3745353b532d3a37",
        )


def test_fetch_commit_yaml_and_possibly_store_only_commit_yaml(
    dbsession, mocker, mock_configuration
):
    commit = CommitFactory.create()
    get_source_result = {
        "content": "\n".join(["codecov:", "  notify:", "    require_ci_to_pass: yes"])
    }
    list_top_level_files_result = [
        {"name": ".gitignore", "path": ".gitignore", "type": "file"},
        {"name": ".travis.yml", "path": ".travis.yml", "type": "file"},
        {"name": "README.rst", "path": "README.rst", "type": "file"},
        {"name": "awesome", "path": "awesome", "type": "folder"},
        {"name": "codecov", "path": "codecov", "type": "file"},
        {"name": "codecov.yaml", "path": "codecov.yaml", "type": "file"},
        {"name": "tests", "path": "tests", "type": "folder"},
    ]
    repository_service = mocker.MagicMock(
        list_top_level_files=mock.AsyncMock(return_value=list_top_level_files_result),
        get_source=mock.AsyncMock(return_value=get_source_result),
    )

    result = fetch_commit_yaml_and_possibly_store(commit, repository_service)
    expected_result = {"codecov": {"notify": {}, "require_ci_to_pass": True}}
    assert result.to_dict() == expected_result
    repository_service.get_source.assert_called_with("codecov.yaml", commit.commitid)
    repository_service.list_top_level_files.assert_called_with(commit.commitid)


def test_fetch_commit_yaml_and_possibly_store_commit_yaml_and_base_yaml(
    dbsession, mock_configuration, mocker
):
    mock_configuration.set_params({"site": {"coverage": {"precision": 14}}})
    commit = CommitFactory.create()
    get_source_result = {
        "content": "\n".join(["codecov:", "  notify:", "    require_ci_to_pass: yes"])
    }
    list_top_level_files_result = [
        {"name": ".travis.yml", "path": ".travis.yml", "type": "file"},
        {"name": "awesome", "path": "awesome", "type": "folder"},
        {"name": ".codecov.yaml", "path": ".codecov.yaml", "type": "file"},
    ]
    repository_service = mocker.MagicMock(
        list_top_level_files=mock.AsyncMock(return_value=list_top_level_files_result),
        get_source=mock.AsyncMock(return_value=get_source_result),
    )

    result = fetch_commit_yaml_and_possibly_store(commit, repository_service)
    expected_result = {
        "codecov": {"notify": {}, "require_ci_to_pass": True},
        "coverage": {"precision": 14},
    }
    assert result.to_dict() == expected_result
    repository_service.get_source.assert_called_with(".codecov.yaml", commit.commitid)
    repository_service.list_top_level_files.assert_called_with(commit.commitid)


def test_fetch_commit_yaml_and_possibly_store_commit_yaml_and_repo_yaml(
    dbsession, mock_configuration, mocker
):
    mock_configuration.set_params({"site": {"coverage": {"precision": 14}}})
    commit = CommitFactory.create(
        repository__yaml={"codecov": {"max_report_age": "1y ago"}},
        repository__branch="supeduperbranch",
        branch="supeduperbranch",
    )
    get_source_result = {
        "content": "\n".join(["codecov:", "  notify:", "    require_ci_to_pass: yes"])
    }
    list_top_level_files_result = [
        {"name": ".gitignore", "path": ".gitignore", "type": "file"},
        {"name": ".codecov.yaml", "path": ".codecov.yaml", "type": "file"},
        {"name": "tests", "path": "tests", "type": "folder"},
    ]
    repository_service = mocker.MagicMock(
        list_top_level_files=mock.AsyncMock(return_value=list_top_level_files_result),
        get_source=mock.AsyncMock(return_value=get_source_result),
    )

    result = fetch_commit_yaml_and_possibly_store(commit, repository_service)
    expected_result = {
        "codecov": {"notify": {}, "require_ci_to_pass": True},
        "coverage": {"precision": 14},
    }
    assert result.to_dict() == expected_result
    assert commit.repository.yaml == {
        "codecov": {"notify": {}, "require_ci_to_pass": True}
    }
    repository_service.get_source.assert_called_with(".codecov.yaml", commit.commitid)
    repository_service.list_top_level_files.assert_called_with(commit.commitid)


def test_fetch_commit_yaml_and_possibly_store_commit_yaml_no_commit_yaml(
    dbsession, mock_configuration, mocker
):
    mock_configuration.set_params({"site": {"coverage": {"round": "up"}}})
    commit = CommitFactory.create(
        repository__owner__yaml={"coverage": {"precision": 2}},
        repository__yaml={"codecov": {"max_report_age": "1y ago"}},
        repository__branch="supeduperbranch",
        branch="supeduperbranch",
    )
    repository_service = mocker.MagicMock(
        list_top_level_files=mock.AsyncMock(
            side_effect=TorngitClientError(404, "fake_response", "message")
        )
    )

    result = fetch_commit_yaml_and_possibly_store(commit, repository_service)
    expected_result = {
        "coverage": {"precision": 2, "round": "up"},
        "codecov": {"max_report_age": "1y ago"},
    }
    assert result.to_dict() == expected_result
    assert commit.repository.yaml == {"codecov": {"max_report_age": "1y ago"}}


def test_fetch_commit_yaml_and_possibly_store_commit_yaml_invalid_commit_yaml(
    dbsession, mock_configuration, mocker
):
    mock_configuration.set_params({"site": {"comment": {"behavior": "new"}}})
    commit = CommitFactory.create(
        repository__owner__yaml={"coverage": {"precision": 2}},
        # User needs to be less than PATCH_CENTRIC_DEFAULT_TIME_START
        repository__owner__createstamp=datetime.fromisoformat(
            "2024-03-30 00:00:00.000+00:00"
        ),
        repository__yaml={"codecov": {"max_report_age": "1y ago"}},
        repository__branch="supeduperbranch",
        branch="supeduperbranch",
    )
    dbsession.add(commit)
    get_source_result = {
        "content": "\n".join(["bad_key:", "  notify:", "    require_ci_to_pass: yes"])
    }
    list_top_level_files_result = [
        {"name": ".gitignore", "path": ".gitignore", "type": "file"},
        {"name": ".codecov.yaml", "path": ".codecov.yaml", "type": "file"},
        {"name": "tests", "path": "tests", "type": "folder"},
    ]
    repository_service = mocker.MagicMock(
        list_top_level_files=mock.AsyncMock(return_value=list_top_level_files_result),
        get_source=mock.AsyncMock(return_value=get_source_result),
    )

    result = fetch_commit_yaml_and_possibly_store(commit, repository_service)
    expected_result = {
        "coverage": {"precision": 2},
        "codecov": {"max_report_age": "1y ago"},
        "comment": {"behavior": "new"},
    }
    assert result.to_dict() == expected_result
    assert commit.repository.yaml == {"codecov": {"max_report_age": "1y ago"}}
