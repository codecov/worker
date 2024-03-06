import pytest

from database.models.core import Commit, Repository
from database.tests.factories.core import CommitFactory, RepositoryFactory
from services.archive import ArchiveService
from tasks.mutation_test_upload import MutationTestUploadTask


def test_mutation_upload_task_call(
    mocker,
    mock_configuration,
    dbsession,
    mock_storage,
    mock_redis,
    celery_app,
):
    repository: Repository = RepositoryFactory.create(name="the-repo")
    commit: Commit = CommitFactory.create(repository=repository)
    dbsession.add(repository)
    dbsession.add(commit)
    dbsession.commit()
    fake_data = b"some fake data saved in the uploaded coverage report\nwe don't know the format yet..."
    repo_hash = ArchiveService.get_archive_hash(commit.repository)

    chunks_url = f"v4/repos/{repo_hash}/commits/{commit.commitid}/chunks.txt"
    mock_storage.write_file("archive", chunks_url, fake_data)

    task_data = dict(
        repoid=repository.repoid, upload_path=chunks_url, commitid=commit.commitid
    )
    res = MutationTestUploadTask().run_impl(dbsession, **task_data)
    assert res == fake_data.decode()
