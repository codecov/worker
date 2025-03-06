import pytest
from shared.django_apps.reports.models import CommitReport, ReportDetails
from shared.django_apps.reports.tests.factories import ReportDetailsFactory

from services.cleanup.regular import run_regular_cleanup
from services.cleanup.utils import CleanupResult, CleanupSummary


@pytest.mark.django_db
def test_deletes_reportdetails(mock_archive_storage):
    mock_archive_storage.write_file("archive", "some_random_path", b"some random data")

    ReportDetailsFactory()
    ReportDetailsFactory(_files_array_storage_path="some_random_path")

    # the parent which is being created by the factory:
    assert CommitReport.objects.all().count() == 2
    assert ReportDetails.objects.all().count() == 2
    assert len(mock_archive_storage.storage["archive"]) == 1

    summary = run_regular_cleanup()

    assert summary == CleanupSummary(
        CleanupResult(2, 1),
        {
            ReportDetails: CleanupResult(2, 1),
        },
    )

    assert CommitReport.objects.all().count() == 2
    assert ReportDetails.objects.all().count() == 0
    assert len(mock_archive_storage.storage["archive"]) == 0
