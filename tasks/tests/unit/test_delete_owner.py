from pathlib import Path

import pytest
from shared.django_apps.codecov_auth.models import Owner
from shared.django_apps.codecov_auth.tests.factories import OwnerFactory
from shared.django_apps.compare.models import CommitComparison
from shared.django_apps.compare.tests.factories import CommitComparisonFactory
from shared.django_apps.core.models import Branch, Commit, Pull, Repository
from shared.django_apps.core.tests.factories import (
    CommitFactory,
    RepositoryFactory,
)

from services.cleanup.utils import CleanupResult, CleanupSummary
from tasks.delete_owner import DeleteOwnerTask

here = Path(__file__)


@pytest.mark.django_db(databases=["timeseries", "default"], transaction=True)
def test_delete_owner_deletes_owner_with_ownerid(mock_storage):
    user = OwnerFactory()
    repo = RepositoryFactory(author=user)
    CommitFactory(repository=repo, author=user)
    # NOTE: the commit creates an implicit `Branch` and `Pull`

    res = DeleteOwnerTask().run_impl({}, user.ownerid)

    assert res == CleanupSummary(
        CleanupResult(5),
        {
            Branch: CleanupResult(1),
            Commit: CleanupResult(1),
            Owner: CleanupResult(1),
            Pull: CleanupResult(1),
            Repository: CleanupResult(1),
        },
    )

    assert Branch.objects.count() == 0
    assert Commit.objects.count() == 0
    assert Owner.objects.count() == 0
    assert Pull.objects.count() == 0
    assert Repository.objects.count() == 0


@pytest.mark.django_db(databases=["timeseries", "default"], transaction=True)
def test_delete_owner_deletes_owner_with_commit_compares(mock_storage):
    user = OwnerFactory()
    repo = RepositoryFactory(author=user)

    base_commit = CommitFactory(repository=repo, author=user)
    compare_commit = CommitFactory(repository=repo, author=user)
    CommitComparisonFactory(base_commit=base_commit, compare_commit=compare_commit)

    res = DeleteOwnerTask().run_impl({}, user.ownerid)

    assert res == CleanupSummary(
        CleanupResult(7),
        {
            Branch: CleanupResult(1),
            Commit: CleanupResult(2),
            CommitComparison: CleanupResult(1),
            Owner: CleanupResult(1),
            Pull: CleanupResult(1),
            Repository: CleanupResult(1),
        },
    )

    assert Branch.objects.count() == 0
    assert Commit.objects.count() == 0
    assert CommitComparison.objects.count() == 0
    assert Owner.objects.count() == 0
    assert Pull.objects.count() == 0
    assert Repository.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_delete_owner_from_orgs_removes_ownerid_from_organizations_of_related_owners(
    mock_storage,
):
    org = OwnerFactory()

    user_1 = OwnerFactory(organizations=[org.ownerid])
    user_2 = OwnerFactory(organizations=[org.ownerid, user_1.ownerid])

    res = DeleteOwnerTask().run_impl({}, org.ownerid)

    assert res.summary[Owner] == CleanupResult(1)

    user_1 = Owner.objects.get(pk=user_1.ownerid)
    assert user_1.organizations == []
    user_2 = Owner.objects.get(pk=user_2.ownerid)
    assert user_2.organizations == [user_1.ownerid]
