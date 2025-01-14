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
from services.cleanup.utils import CleanupResult, CleanupSummary
from tasks.flush_repo import FlushRepoTask


@pytest.mark.django_db
def test_flush_repo_nothing(dbsession, mock_storage):
    repo = RepositoryFactory.create()
    dbsession.add(repo)
    dbsession.flush()

    task = FlushRepoTask()
    res = task.run_impl(dbsession, repoid=repo.repoid)

    assert res == CleanupSummary(CleanupResult(0, 0), {})


@pytest.mark.django_db
def test_flush_repo_few_of_each_only_db_objects(dbsession, mock_storage):
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

    task = FlushRepoTask()
    res = task.run_impl(dbsession, repoid=repo.repoid)

    assert res == CleanupSummary(CleanupResult(16 + 17 + 23, 0), {})


@pytest.mark.django_db
def test_flush_repo_only_archives(dbsession, mock_storage):
    repo = RepositoryFactory.create()
    dbsession.add(repo)
    dbsession.flush()
    archive_service = ArchiveService(repo)
    for i in range(4):
        archive_service.write_chunks(f"commit_sha{i}", f"data{i}")

    task = FlushRepoTask()
    res = task.run_impl(dbsession, repoid=repo.repoid)

    assert res == CleanupSummary(CleanupResult(0, 4), {})


@pytest.mark.django_db
def test_flush_repo_little_bit_of_everything(dbsession, mock_storage):
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
    res = task.run_impl(dbsession, repoid=repo.repoid)

    assert res == CleanupSummary(CleanupResult(8 + 17 + 23, 4), {})
