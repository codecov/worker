import dataclasses
import itertools
from collections.abc import Callable
from functools import partial

from django.db.models import Model
from django.db.models.query import Q, QuerySet
from shared.api_archive.storage import StorageService
from shared.config import get_config
from shared.django_apps.core.models import Commit, Pull
from shared.django_apps.reports.models import CommitReport, ReportDetails, ReportSession

from services.archive import ArchiveService, MinioEndpoints

DELETE_CHUNKS = 25


# This has all the `Repository` fields needed by `get_archive_hash`
@dataclasses.dataclass
class FakeRepository:
    repoid: int
    service: str
    service_id: str


def cleanup_archivefield(field_name: str, query: QuerySet) -> tuple[int, int]:
    model_field_name = f"_{field_name}_storage_path"
    # query for a non-`None` `field_name`
    storage_query = query.filter(**{f"{model_field_name}__isnull": False}).values_list(
        model_field_name, flat=True
    )

    # and then delete all those files from storage
    storage = StorageService()
    bucket = get_config("services", "minio", "bucket", default="archive")
    cleaned_files = 0
    # TODO: possibly fan out the batches to a thread pool, as the storage requests are IO-bound
    # TODO: do a limit / range query to avoid loading *all* the paths into memory at once
    for batched_paths in itertools.batched(storage_query, DELETE_CHUNKS):
        storage.delete_files(bucket, batched_paths)
        cleaned_files += len(batched_paths)

    cleaned_models, _ = query.delete()

    return (cleaned_models, cleaned_files)


def cleanup_commitreport(query: QuerySet) -> tuple[int, int]:
    coverage_reports = query.filter(
        Q(report_type=None) | Q(report_type="coverage")
    ).values_list(
        "code",
        "commit__commitid",
        "repository__repoid",
        "repository__owner__service",
        "repository__service_id",
    )

    storage = StorageService()
    bucket = get_config("services", "minio", "bucket", default="archive")
    repo_hashes: dict[int, str] = {}
    cleaned_files = 0
    # TODO: figure out a way to run the deletes in batches
    # TODO: possibly fan out the batches to a thread pool, as the storage requests are IO-bound
    # TODO: do a limit / range query to avoid loading *all* the paths into memory at once
    for (
        report_code,
        commit_sha,
        repoid,
        repo_service,
        repo_service_id,
    ) in coverage_reports:
        if repoid not in repo_hashes:
            fake_repo = FakeRepository(
                repoid=repoid, service=repo_service, service_id=repo_service_id
            )
            repo_hashes[repoid] = ArchiveService.get_archive_hash(fake_repo)
        repo_hash = repo_hashes[repoid]

        chunks_file_name = report_code if report_code is not None else "chunks"
        path = MinioEndpoints.chunks.get_path(
            version="v4",
            repo_hash=repo_hash,
            commitid=commit_sha,
            chunks_file_name=chunks_file_name,
        )
        storage.delete_file(bucket, path)
        cleaned_files += 1

    cleaned_models, _ = query.delete()

    return (cleaned_models, cleaned_files)


def cleanup_upload(query: QuerySet) -> tuple[int, int]:
    storage_query = query.values_list("storage_path", flat=True)

    storage = StorageService()
    bucket = get_config("services", "minio", "bucket", default="archive")
    cleaned_files = 0
    # TODO: possibly fan out the batches to a thread pool, as the storage requests are IO-bound
    # TODO: do a limit / range query to avoid loading *all* the paths into memory at once
    for batched_paths in itertools.batched(storage_query, DELETE_CHUNKS):
        storage.delete_files(bucket, batched_paths)
        cleaned_files += len(batched_paths)

    cleaned_models, _ = query.delete()

    return (cleaned_models, cleaned_files)


# All the models that need custom python code for deletions so a bulk `DELETE` query does not work.
MANUAL_CLEANUP: dict[type[Model], Callable[[QuerySet], tuple[int, int]]] = {
    Commit: partial(cleanup_archivefield, "report"),
    Pull: partial(cleanup_archivefield, "flare"),
    ReportDetails: partial(cleanup_archivefield, "files_array"),
    CommitReport: cleanup_commitreport,
    ReportSession: cleanup_upload,
    # TODO: figure out any other models which have files in storage that are not `ArchiveField`
    # TODO: TA is also storing files in GCS
    # TODO: BA is also storing files in GCS
    # TODO: There is also `CompareCommit.report_storage_path`, but that does not seem to be implemented as Django model?
}
