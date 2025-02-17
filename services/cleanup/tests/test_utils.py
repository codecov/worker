import pytest
from django.db import transaction
from shared.django_apps.core.models import Commit
from shared.django_apps.core.tests.factories import (
    CommitFactory,
    OwnerFactory,
    RepositoryFactory,
)

from services.cleanup.cleanup import run_cleanup
from services.cleanup.utils import CleanupResult, CleanupSummary, with_autocommit


@pytest.mark.django_db(transaction=True)
def test_with_autommit(mock_archive_storage):
    mock_archive_storage.write_file("archive", "some_random_path", b"some random data")

    owner = OwnerFactory()
    repo = RepositoryFactory(author=owner)
    CommitFactory(author=owner, repository=repo)
    CommitFactory(
        author=owner, repository=repo, _report_storage_path="some_random_path"
    )
    transaction.commit()

    assert Commit.objects.all().count() == 2

    transaction.set_autocommit(False)
    query = Commit.objects.all()
    summary = run_cleanup(query)
    transaction.rollback()

    # Oops, the transaction was rolled back, but the cleanup job still reports stuff being cleaned up.
    # Not only that, but the files actually *were* deleted, leading to inconsistency
    assert summary == CleanupSummary(
        CleanupResult(2, 1),
        {
            Commit: CleanupResult(2, 1),
        },
    )
    assert Commit.objects.all().count() == 2
    assert len(mock_archive_storage.storage["archive"]) == 0

    with with_autocommit():
        query = Commit.objects.all()
        summary = run_cleanup(query)
        transaction.rollback()  # <- this `rollback` here has no effect, as the cleanup was auto-committed

    assert summary == CleanupSummary(
        CleanupResult(2, 0),
        {
            Commit: CleanupResult(2, 0),
        },
    )
    assert Commit.objects.all().count() == 0
