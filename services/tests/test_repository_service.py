import pytest
from datetime import datetime
import mock

from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitServerUnreachableError,
)

from services.repository import (
    get_repo_provider_service,
    fetch_appropriate_parent_for_commit,
    get_or_create_author,
    update_commit_from_provider_info,
    get_repo_provider_service_by_id,
    fetch_and_update_pull_request_information_from_commit,
    fetch_and_update_pull_request_information,
)
from database.models import Owner
from database.tests.factories import (
    RepositoryFactory,
    OwnerFactory,
    CommitFactory,
    PullFactory,
)


class TestRepositoryServiceTestCase(object):
    def test_get_repo_provider_service(self, dbsession):
        repo = RepositoryFactory.create(
            owner__unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
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
        }
        assert res.data == expected_data
        assert res.token == {
            "username": repo.owner.username,
            "key": "testyftq3ovzkb3zmt823u3t04lkrt9w",
            "secret": None,
        }

    def test_get_repo_provider_service_different_bot(self, dbsession):
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
        }
        assert res.data["repo"] == expected_data["repo"]
        assert res.data == expected_data
        assert res.token == {
            "username": repo.bot.username,
            "key": bot_token,
            "secret": None,
        }

    def test_get_repo_provider_service_no_bot(self, dbsession):
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
        }
        assert res.data == expected_data
        assert res.token == {
            "username": repo.owner.bot.username,
            "key": bot_token,
            "secret": None,
        }

    @pytest.mark.asyncio
    async def test_fetch_appropriate_parent_for_commit_grandparent(
        self, dbsession, mock_repo_provider
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
        self, dbsession, mock_repo_provider
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
        self, dbsession, mock_repo_provider
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
        self, dbsession, mock_repo_provider
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
    async def test_fetch_appropriate_parent_for_commit_grandparent_wrong_repo_with_same(
        self, dbsession, mock_repo_provider
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
    async def test_fetch_appropriate_parent_for_commit_direct_parent(
        self, dbsession, mock_repo_provider
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

    def test_get_or_create_author_doesnt_exist(self, dbsession):
        service = "github"
        author_id = "123"
        username = "username"
        email = "email"
        name = "name"
        author = get_or_create_author(
            dbsession, service, author_id, username, email, name
        )
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

    def test_get_or_create_author_already_exists(self, dbsession):
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
        author = get_or_create_author(
            dbsession, service, author_id, username, email, name
        )
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

    @pytest.mark.asyncio
    async def test_update_commit_from_provider_info_no_author_id(
        self, dbsession, mocker
    ):
        possible_parent_commit = CommitFactory.create(
            message="possible_parent_commit", pullid=None
        )
        commit = CommitFactory.create(
            message="",
            author=None,
            pullid=1,
            totals=None,
            report_json=None,
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
        get_pull_request_result = {"head": {"branch": "newbranchyeah"}}
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
        assert commit.report_json is None
        assert commit.branch == "newbranchyeah"
        assert commit.merged is False
        assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
        assert commit.parent_commit_id == possible_parent_commit.commitid
        assert commit.state == "complete"

    @pytest.mark.asyncio
    async def test_update_commit_from_provider_info_no_pullid_on_defaultbranch(
        self, dbsession, mocker, mock_repo_provider
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
            report_json=None,
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
        assert commit.report_json is None
        assert commit.branch == "superbranch"
        assert commit.merged is True
        assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
        assert commit.parent_commit_id == possible_parent_commit.commitid
        assert commit.state == "complete"

    @pytest.mark.asyncio
    async def test_update_commit_from_provider_info_no_pullid_not_on_defaultbranch(
        self, dbsession, mocker, mock_repo_provider
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
            report_json=None,
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
        assert commit.report_json is None
        assert commit.branch == "papapa"
        assert commit.merged is False
        assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
        assert commit.parent_commit_id == possible_parent_commit.commitid
        assert commit.state == "complete"

    @pytest.mark.asyncio
    async def test_update_commit_from_provider_info_with_author_id(
        self, dbsession, mocker
    ):
        possible_parent_commit = CommitFactory.create(
            message="possible_parent_commit", pullid=None
        )
        commit = CommitFactory.create(
            message="",
            author=None,
            pullid=1,
            totals=None,
            report_json=None,
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
        get_pull_request_result = {"head": {"branch": "newbranchyeah"}}
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
        assert commit.report_json is None
        assert commit.branch == "newbranchyeah"
        assert commit.parent_commit_id == possible_parent_commit.commitid
        assert commit.state == "complete"
        assert commit.author is not None
        assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
        assert commit.author.username == "author_username"

    @pytest.mark.asyncio
    async def test_update_commit_from_provider_info_bitbucket_merge(
        self, dbsession, mocker
    ):
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
            report_json=None,
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
        assert commit.report_json is None
        assert commit.branch == "thebasebranch"
        assert commit.parent_commit_id == possible_parent_commit.commitid
        assert commit.state == "complete"
        assert commit.author is not None
        assert commit.timestamp == datetime(2018, 7, 9, 23, 39, 20)
        assert commit.author.username == "author_username"

    @pytest.mark.asyncio
    async def test_get_repo_gh_no_integration(self, dbsession, mocker):
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
        }
        assert res.data["repo"] == expected_data["repo"]
        assert res.data == expected_data
        assert res.token == {
            "username": "1nf1n1t3l00p",
            "key": "bcaa0dc0c66b4a8c8c65ac919a1a91aa",
            "secret": None,
        }


class TestPullRequestFetcher(object):
    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_from_commit_new_pull_commits_in_place(
        self, dbsession, mocker
    ):
        now = datetime.utcnow()
        commit = CommitFactory.create(
            message="", pullid=1, totals=None, report_json=None,
        )
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
        assert res.flare is None
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
        self, dbsession, mocker
    ):
        now = datetime.utcnow()
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(repository=repository, author=None)
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            report_json=None,
            repository=repository,
        )
        base_commit = CommitFactory.create(repository=repository, branch="master")
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
        assert res.flare is None
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
        self, dbsession, mocker
    ):
        now = datetime.utcnow()
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(
            repository=repository, title="purposelly bad title", author=None
        )
        second_pull = PullFactory.create(repository=repository)
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            report_json=None,
            repository=repository,
        )
        base_commit = CommitFactory.create(repository=repository, branch="master")
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
        assert res.flare is None
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
        self, dbsession, mocker
    ):
        now = datetime.utcnow()
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(repository=repository, author=None)
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            report_json=None,
            repository=repository,
        )
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        dbsession.add(pull)
        dbsession.add(commit)
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
        assert res.flare is None
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
        self, dbsession, mocker
    ):
        now = datetime.utcnow()
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(repository=repository, author=None)
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            report_json=None,
            repository=repository,
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
        assert res.flare is None
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
        self, dbsession, mocker
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        commit = CommitFactory.create(
            message="",
            pullid=None,
            totals=None,
            report_json=None,
            repository=repository,
        )
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        dbsession.add(commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            find_pull_request=mock.AsyncMock(
                side_effect=TorngitClientError(422, "response", "message")
            ),
        )
        res = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        assert res is None

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_torngitexception_getting_pull(
        self, dbsession, mocker
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        commit = CommitFactory.create(
            message="",
            pullid="123",
            totals=None,
            report_json=None,
            repository=repository,
        )
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        dbsession.add(commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(
                side_effect=TorngitObjectNotFoundError("response", "message")
            ),
        )
        res = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        assert res.database_pull is None
        assert res.provider_pull is None

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_torngitserverexception_getting_pull(
        self, dbsession, mocker
    ):
        pull = PullFactory.create()
        dbsession.add(pull)
        dbsession.flush()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(
                side_effect=TorngitServerUnreachableError()
            ),
        )
        res = await fetch_and_update_pull_request_information(
            repository_service, dbsession, pull.repoid, pull.pullid, current_yaml
        )
        assert res.database_pull == pull
        assert res.provider_pull is None

    @pytest.mark.asyncio
    async def test_fetch_and_update_pull_request_information_notfound_pull_already_exists(
        self, dbsession, mocker
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(repository=repository)
        dbsession.add(pull)
        commit = CommitFactory.create(
            message="",
            pullid=pull.pullid,
            totals=None,
            report_json=None,
            repository=repository,
        )
        compared_to_commit = CommitFactory.create(
            repository=repository, branch="master", merged=True
        )
        dbsession.add(commit)
        dbsession.add(compared_to_commit)
        dbsession.flush()
        current_yaml = {}
        repository_service = mocker.MagicMock(
            get_pull_request=mock.AsyncMock(
                side_effect=TorngitObjectNotFoundError("response", "message")
            ),
        )
        res = await fetch_and_update_pull_request_information_from_commit(
            repository_service, commit, current_yaml
        )
        assert res.database_pull == pull
