import pytest

from database.tests.factories import (
    BranchFactory,
    CommitFactory,
    CompareCommitFactory,
    PullFactory,
    RepositoryFactory,
)
from database.tests.factories.reports import CompareFlagFactory, RepositoryFlagFactory
from services.archive import ArchiveService
from tasks.flush_repo import FlushRepoTask, FlushRepoTaskReturnType


class TestFlushRepo(object):
    @pytest.mark.asyncio
    async def test_flush_repo_nothing(self, dbsession, mock_storage):
        task = FlushRepoTask()
        repo = RepositoryFactory.create()
        dbsession.add(repo)
        dbsession.flush()
        res = await task.run_async(dbsession, repoid=repo.repoid)
        assert res == FlushRepoTaskReturnType(
            **{
                "delete_branches_count": 0,
                "deleted_archives_count": 0,
                "deleted_commits_count": 0,
                "deleted_pulls_count": 0,
            }
        )

    @pytest.mark.asyncio
    async def test_flush_repo_few_of_each_only_db_objects(
        self, dbsession, mock_storage
    ):
        task = FlushRepoTask()
        repo = RepositoryFactory.create()
        dbsession.add(repo)
        dbsession.flush()
        flag = RepositoryFlagFactory.create(repository=repo)
        dbsession.add(flag)
        for i in range(8):
            commit = CommitFactory.create(repository=repo)
            dbsession.add(commit)
        for i in range(4):
            base_commit = CommitFactory.create(repository=repo)
            head_commit = CommitFactory.create(repository=repo)
            comparison = CompareCommitFactory.create(
                base_commit=base_commit, compare_commit=head_commit
            )
            dbsession.add(base_commit)
            dbsession.add(head_commit)
            dbsession.add(comparison)

            flag_comparison = CompareFlagFactory.create(
                commit_comparison=comparison, repositoryflag=flag
            )
            dbsession.add(flag_comparison)
        for i in range(17):
            pull = PullFactory.create(repository=repo, pullid=i + 100)
            dbsession.add(pull)
        for i in range(23):
            branch = BranchFactory.create(repository=repo)
            dbsession.add(branch)
        dbsession.flush()
        res = await task.run_async(dbsession, repoid=repo.repoid)
        assert res == FlushRepoTaskReturnType(
            **{
                "delete_branches_count": 23,
                "deleted_archives_count": 0,
                "deleted_commits_count": 16,
                "deleted_pulls_count": 17,
            }
        )

    @pytest.mark.asyncio
    async def test_flush_repo_only_archives(self, dbsession, mock_storage):
        repo = RepositoryFactory.create()
        dbsession.add(repo)
        dbsession.flush()
        archive_service = ArchiveService(repo)
        for i in range(4):
            archive_service.write_chunks(f"commit_sha{i}", f"data{i}")
        task = FlushRepoTask()
        res = await task.run_async(dbsession, repoid=repo.repoid)
        assert res == FlushRepoTaskReturnType(
            **{
                "delete_branches_count": 0,
                "deleted_archives_count": 4,
                "deleted_commits_count": 0,
                "deleted_pulls_count": 0,
            }
        )

    @pytest.mark.asyncio
    async def test_flush_repo_little_bit_of_everything(self, dbsession, mock_storage):
        repo = RepositoryFactory.create()
        dbsession.add(repo)
        dbsession.flush()
        archive_service = ArchiveService(repo)
        for i in range(8):
            commit = CommitFactory.create(repository=repo)
            dbsession.add(commit)
        for i in range(17):
            pull = PullFactory.create(repository=repo, pullid=i + 100)
            dbsession.add(pull)
        for i in range(23):
            branch = BranchFactory.create(repository=repo)
            dbsession.add(branch)
        dbsession.flush()
        for i in range(4):
            archive_service.write_chunks(f"commit_sha{i}", f"data{i}")
        task = FlushRepoTask()
        res = await task.run_async(dbsession, repoid=repo.repoid)
        assert res == FlushRepoTaskReturnType(
            **{
                "delete_branches_count": 23,
                "deleted_archives_count": 4,
                "deleted_commits_count": 8,
                "deleted_pulls_count": 17,
            }
        )
        dbsession.flush()
        dbsession.refresh(repo)
        # Those assertions are almost tautological. If they start being a
        # problem, don't hesitate to delete them
