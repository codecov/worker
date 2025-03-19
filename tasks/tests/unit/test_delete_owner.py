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
from shared.django_apps.reports.models import (
    CommitReport,
    DailyTestRollup,
    Test,
    TestInstance,
)
from shared.django_apps.reports.models import ReportSession as Upload
from shared.django_apps.reports.tests.factories import (
    CommitReportFactory,
    DailyTestRollupFactory,
    TestFactory,
    TestInstanceFactory,
    UploadFactory,
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

    report = CommitReportFactory(commit=base_commit)
    upload = UploadFactory(report=report)
    test = TestFactory(repository=repo)
    TestInstanceFactory(test=test, upload=upload)
    DailyTestRollupFactory(test=test, repoid=repo.repoid)

    # This test factory implicitly creates:
    # - Test with a Repository and an Owner,
    # - An Upload with a CommitReport, a Commit that has a different Owner and
    #   one more Repository with yet another different Owner.
    # And then also a Branch and a Pull via DB triggers because of the Commit.
    remaining = TestInstanceFactory()

    res = DeleteOwnerTask().run_impl({}, user.ownerid)

    assert res == CleanupSummary(
        CleanupResult(12),
        {
            Branch: CleanupResult(1),
            Commit: CleanupResult(2),
            CommitComparison: CleanupResult(1),
            Owner: CleanupResult(1),
            Pull: CleanupResult(1),
            Repository: CleanupResult(1),
            CommitReport: CleanupResult(1),
            Upload: CleanupResult(1),
            Test: CleanupResult(1),
            TestInstance: CleanupResult(1),
            DailyTestRollup: CleanupResult(1),
        },
    )

    assert list(TestInstance.objects.all()) == [remaining]
    # See the comment above why we have all of these objects
    assert Branch.objects.count() == 1
    assert Commit.objects.count() == 1
    assert CommitComparison.objects.count() == 0
    assert Owner.objects.count() == 3
    assert Pull.objects.count() == 1
    assert Repository.objects.count() == 2
    assert CommitReport.objects.count() == 1
    assert Upload.objects.count() == 1
    assert Test.objects.count() == 1
    assert DailyTestRollup.objects.count() == 0


@pytest.mark.django_db(databases=["timeseries", "default"], transaction=True)
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
