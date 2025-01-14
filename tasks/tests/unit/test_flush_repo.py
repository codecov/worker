import pytest
from shared.django_apps.compare.models import CommitComparison, FlagComparison
from shared.django_apps.compare.tests.factories import (
    CommitComparisonFactory,
    FlagComparisonFactory,
)
from shared.django_apps.core.models import Branch, Commit, Pull, Repository
from shared.django_apps.core.tests.factories import (
    BranchFactory,
    CommitFactory,
    PullFactory,
    RepositoryFactory,
)
from shared.django_apps.reports.models import CommitReport, RepositoryFlag
from shared.django_apps.reports.models import ReportSession as Upload
from shared.django_apps.reports.tests.factories import (
    CommitReportFactory,
    RepositoryFlagFactory,
    UploadFactory,
)

from services.archive import ArchiveService
from services.cleanup.utils import CleanupResult, CleanupSummary
from tasks.flush_repo import FlushRepoTask


@pytest.mark.django_db
def test_flush_repo_nothing(mock_storage):
    repo = RepositoryFactory()

    task = FlushRepoTask()
    res = task.run_impl({}, repoid=repo.repoid)

    assert res == CleanupSummary(
        CleanupResult(1),
        {
            Repository: CleanupResult(1),
        },
    )


@pytest.mark.django_db
def test_flush_repo_few_of_each_only_db_objects(mock_storage):
    repo = RepositoryFactory()
    flag = RepositoryFlagFactory(repository=repo)

    for i in range(8):
        CommitFactory(repository=repo)

    for i in range(4):
        base_commit = CommitFactory(repository=repo)
        head_commit = CommitFactory(repository=repo)
        comparison = CommitComparisonFactory(
            base_commit=base_commit, compare_commit=head_commit
        )

        FlagComparisonFactory(commit_comparison=comparison, repositoryflag=flag)

    # NOTE: The `CommitFactary` defaults to `branch: main, pullid: 1`
    # This default seems to create models for
    # `Pull` and `Branch` automatically through some kind of trigger?

    for i in range(17):
        PullFactory(repository=repo, pullid=i + 100)

    for i in range(23):
        BranchFactory(repository=repo)

    task = FlushRepoTask()
    res = task.run_impl({}, repoid=repo.repoid)

    assert res == CleanupSummary(
        CleanupResult(24 + 16 + 4 + 4 + 18 + 1 + 1),
        {
            Branch: CleanupResult(24),
            Commit: CleanupResult(16),
            CommitComparison: CleanupResult(4),
            FlagComparison: CleanupResult(4),
            Pull: CleanupResult(18),
            Repository: CleanupResult(1),
            RepositoryFlag: CleanupResult(1),
        },
    )


@pytest.mark.django_db
def test_flush_repo_little_bit_of_everything(mocker, mock_storage):
    repo = RepositoryFactory()
    mocker.patch("services.cleanup.utils.StorageService")
    archive_service = ArchiveService(repo)

    for i in range(8):
        # NOTE: `CommitWithReportFactory` exists, but its only usable from `api`,
        # because of unresolved imports
        commit = CommitFactory(repository=repo)
        commit_report = CommitReportFactory(commit=commit)
        upload = UploadFactory(report=commit_report, storage_path=f"upload{i}")

        archive_service.write_chunks(commit.commitid, f"chunksdata{i}")
        archive_service.write_file(upload.storage_path, f"uploaddata{i}")

    for i in range(17):
        PullFactory(repository=repo, pullid=i + 100)

    for i in range(23):
        BranchFactory(repository=repo)

    archive = mock_storage.storage["archive"]
    assert len(archive) == 16

    task = FlushRepoTask()
    res = task.run_impl({}, repoid=repo.repoid)

    assert res == CleanupSummary(
        CleanupResult(24 + 8 + 8 + 18 + 1 + 8, 16),
        {
            Branch: CleanupResult(24),
            Commit: CleanupResult(8),
            CommitReport: CleanupResult(8, 8),
            Pull: CleanupResult(18),
            Repository: CleanupResult(1),
            Upload: CleanupResult(8, 8),
        },
    )
    assert len(archive) == 0
