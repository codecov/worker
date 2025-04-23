from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from shared.bundle_analysis import StoragePaths
from shared.django_apps.core.tests.factories import CommitFactory, RepositoryFactory
from shared.django_apps.reports.models import ReportSession as Upload
from shared.django_apps.reports.tests.factories import (
    CommitReportFactory,
    UploadFactory,
)

from services.archive import ArchiveService
from services.cleanup.regular import create_upload_cleanup_jobs, run_regular_cleanup
from services.cleanup.tests.test_relations import dump_delete_queries
from services.cleanup.utils import CleanupResult, CleanupSummary


@pytest.mark.django_db
@freeze_time("2025-04-23T00:00:00Z")
def test_runs_regular_cleanup(mock_storage):
    repo = RepositoryFactory()
    archive_service = ArchiveService(repo)

    for i, timestamp in enumerate(
        [
            datetime(2024, 8, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        ]
    ):
        commit = CommitFactory(repository=repo)

        commit_report = CommitReportFactory(commit=commit)
        with freeze_time(timestamp):
            upload = UploadFactory(report=commit_report, storage_path=f"upload{i}")

        archive_service.write_chunks(commit.commitid, f"chunks_data{i}")
        archive_service.write_file(upload.storage_path, f"upload_data{i}")

        ba_report = CommitReportFactory(commit=commit, report_type="bundle_analysis")
        with freeze_time(timestamp):
            ba_upload = UploadFactory(report=ba_report, storage_path=f"ba_upload{i}")

        ba_report_path = StoragePaths.bundle_report.path(
            repo_key=archive_service.storage_hash, report_key=ba_report.external_id
        )
        archive_service.storage.write_file(
            "bundle-analysis", ba_report_path, f"ba_report_data{i}"
        )
        archive_service.storage.write_file(
            "bundle-analysis", ba_upload.storage_path, f"ba_upload_data{i}"
        )

    archive = mock_storage.storage["archive"]
    ba_archive = mock_storage.storage["bundle-analysis"]
    assert len(archive) == 4
    assert len(ba_archive) == 4

    summary = run_regular_cleanup()

    assert summary == CleanupSummary(
        CleanupResult(2, 2),
        {
            Upload: CleanupResult(2, 2),
        },
    )
    assert len(archive) == 3
    assert len(ba_archive) == 3


@pytest.mark.django_db
@freeze_time("2025-04-23T00:00:00Z")
def test_generates_sliced_upload_cleanups(snapshot):
    # we expect the last slice to delete uploads older than `2024-11-24`,
    # or 120 days older than the frozen timestamp given above.
    latest = create_upload_cleanup_jobs()[-1]

    assert dump_delete_queries(latest) == snapshot("upload.txt")
