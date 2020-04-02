from pathlib import Path
from asyncio import Future
import pytest

from redis.exceptions import LockError
from torngit.exceptions import TorngitClientError

from tasks.sync_pull import PullSyncTask
from database.tests.factories import RepositoryFactory, CommitFactory, PullFactory
from services.repository import EnrichedPull
from helpers.exceptions import RepositoryWithoutValidBotError

here = Path(__file__)


class TestPullSyncTask(object):
    def test_update_pull_commits_merged(self, dbsession):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository,)
        pull = PullFactory.create(
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
            state="merged",
        )
        pullid = pull.pullid
        base_commit.pullid = pullid
        head_commit.pullid = pullid
        first_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        second_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        third_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        fourth_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        dbsession.add(pull)
        dbsession.add(first_commit)
        dbsession.add(second_commit)
        dbsession.add(third_commit)
        dbsession.add(fourth_commit)
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.flush()
        task = PullSyncTask()
        enriched_pull = EnrichedPull(
            database_pull=pull, provider_pull=dict(base=dict(branch="lookatthis")),
        )
        commits = [first_commit.commitid, third_commit.commitid]
        res = task.update_pull_commits(enriched_pull, commits)
        assert res == {"merged_count": 2, "soft_deleted_count": 2}
        dbsession.refresh(first_commit)
        dbsession.refresh(second_commit)
        dbsession.refresh(third_commit)
        dbsession.refresh(fourth_commit)
        assert not first_commit.deleted
        assert second_commit.deleted
        assert not third_commit.deleted
        assert fourth_commit.deleted
        assert first_commit.merged
        assert not second_commit.merged
        assert third_commit.merged
        assert not fourth_commit.merged
        assert first_commit.branch == "lookatthis"
        assert third_commit.branch == "lookatthis"

    def test_update_pull_commits_not_merged(self, dbsession):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository,)
        pull = PullFactory.create(
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
            state="open",
        )
        pullid = pull.pullid
        base_commit.pullid = pullid
        head_commit.pullid = pullid
        first_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        second_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        third_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        fourth_commit = CommitFactory.create(
            repository=repository, pullid=pullid, merged=False
        )
        dbsession.add(pull)
        dbsession.add(first_commit)
        dbsession.add(second_commit)
        dbsession.add(third_commit)
        dbsession.add(fourth_commit)
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.flush()
        task = PullSyncTask()
        enriched_pull = EnrichedPull(
            database_pull=pull, provider_pull=dict(base=dict(branch="lookatthis")),
        )
        commits = [first_commit.commitid, third_commit.commitid]
        res = task.update_pull_commits(enriched_pull, commits)
        assert res == {"merged_count": 0, "soft_deleted_count": 2}
        dbsession.refresh(first_commit)
        dbsession.refresh(second_commit)
        dbsession.refresh(third_commit)
        dbsession.refresh(fourth_commit)
        assert not first_commit.deleted
        assert second_commit.deleted
        assert not third_commit.deleted
        assert fourth_commit.deleted
        assert not first_commit.merged
        assert not second_commit.merged
        assert not third_commit.merged
        assert not fourth_commit.merged

    @pytest.mark.asyncio
    async def test_call_pullsync_task_no_head_commit(
        self, dbsession, mocker, mock_redis
    ):
        task = PullSyncTask()
        pull = PullFactory.create(head="head_commit_nonexistent_sha", state="open",)
        dbsession.add(pull)
        dbsession.flush()
        mocked_fetch_pr = mocker.patch(
            "tasks.sync_pull.fetch_and_update_pull_request_information",
            return_value=Future(),
        )
        mocked_fetch_pr.return_value.set_result(
            EnrichedPull(database_pull=pull, provider_pull={})
        )
        res = await task.run_async(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "no_head",
        }

    @pytest.mark.asyncio
    async def test_call_pullsync_task_nolock(self, dbsession, mock_redis):
        task = PullSyncTask()
        pull = PullFactory.create(state="open",)
        dbsession.add(pull)
        dbsession.flush()
        mock_redis.lock.return_value.__enter__.side_effect = LockError
        res = await task.run_async(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "unable_fetch_lock",
        }

    @pytest.mark.asyncio
    async def test_call_pullsync_task_no_database_pull(
        self, dbsession, mocker, mock_redis
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        task = PullSyncTask()
        mocked_fetch_pr = mocker.patch(
            "tasks.sync_pull.fetch_and_update_pull_request_information",
            return_value=Future(),
        )
        mocked_fetch_pr.return_value.set_result(
            EnrichedPull(database_pull=None, provider_pull=None)
        )
        res = await task.run_async(dbsession, repoid=repository.repoid, pullid=99)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "no_db_pull",
        }

    @pytest.mark.asyncio
    async def test_call_pullsync_task_no_provider_pull_only(
        self, dbsession, mocker, mock_redis
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(state="open", repository=repository)
        dbsession.add(pull)
        dbsession.flush()
        task = PullSyncTask()
        mocked_fetch_pr = mocker.patch(
            "tasks.sync_pull.fetch_and_update_pull_request_information",
            return_value=Future(),
        )
        mocked_fetch_pr.return_value.set_result(
            EnrichedPull(database_pull=pull, provider_pull=None)
        )
        res = await task.run_async(dbsession, repoid=repository.repoid, pullid=99)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "not_in_provider",
        }

    @pytest.mark.asyncio
    async def test_call_pullsync_no_bot(self, dbsession, mock_redis, mocker):
        task = PullSyncTask()
        pull = PullFactory.create(state="open",)
        dbsession.add(pull)
        dbsession.flush()
        mocker.patch(
            "tasks.sync_pull.get_repo_provider_service",
            side_effect=RepositoryWithoutValidBotError(),
        )
        res = await task.run_async(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "no_bot",
        }

    @pytest.mark.asyncio
    async def test_call_pullsync_no_permissions_get_compare(
        self, dbsession, mock_redis, mocker, mock_repo_provider, mock_storage
    ):
        mocker.patch.object(PullSyncTask, "app")
        task = PullSyncTask()
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository,)
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        pull = PullFactory.create(
            state="open",
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
        )
        dbsession.add(pull)
        dbsession.flush()
        mocked_fetch_pr = mocker.patch(
            "tasks.sync_pull.fetch_and_update_pull_request_information",
            return_value=Future(),
        )
        mocked_fetch_pr.return_value.set_result(
            EnrichedPull(database_pull=pull, provider_pull={"head"})
        )
        mock_repo_provider.get_compare.return_value = Future()
        mock_repo_provider.get_compare.return_value.set_exception(
            TorngitClientError(403, "response", "message")
        )
        res = await task.run_async(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": True,
            "pull_updated": True,
            "reason": "success",
        }

    @pytest.mark.asyncio
    async def test_run_async_unobtainable_lock(self, dbsession, mocker, mock_redis):
        pull = PullFactory.create()
        dbsession.add(pull)
        dbsession.flush()
        mock_redis.lock.side_effect = LockError()
        mock_redis.exists.return_value = True
        task = PullSyncTask()
        task.request.retries = 0
        res = await task.run_async(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "unable_fetch_lock",
        }
