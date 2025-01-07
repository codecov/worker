import dataclasses
import itertools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from django.db.models import Model
from django.db.models.query import Q, QuerySet
from shared.api_archive.storage import StorageService
from shared.config import get_config
from shared.django_apps.core.models import Commit, Pull
from shared.django_apps.reports.models import CommitReport, ReportDetails, ReportSession

from services.archive import ArchiveService, MinioEndpoints
from services.cleanup.utils import CleanupContext

MANUAL_QUERY_BATCHSIZE = 1_000
DELETE_FILES_BATCHSIZE = 50


# This has all the `Repository` fields needed by `get_archive_hash`
@dataclasses.dataclass
class FakeRepository:
    repoid: int
    service: str
    service_id: str


def cleanup_files_batched(context: CleanupContext, paths: list[str]) -> int:
    cleaned_files = 0
    # TODO: maybe reuse the executor across calls?
    with ThreadPoolExecutor() as e:
        for batched_paths in itertools.batched(paths, DELETE_FILES_BATCHSIZE):
            e.submit(context.storage.delete_files(context.bucket, batched_paths))

        cleaned_files += len(batched_paths)

    return cleaned_files


def cleanup_archivefield(
    field_name: str, context: CleanupContext, query: QuerySet
) -> tuple[int, int]:
    model_field_name = f"_{field_name}_storage_path"

    # delete `None` `field_name`s right away
    cleaned_models, _ = query.filter(**{f"{model_field_name}__isnull": True}).delete()

    # query for a non-`None` `field_name`
    storage_query = query.filter(**{f"{model_field_name}__isnull": False}).order_by(
        "id"
    )

    # and then delete all those files from storage, using batched queries
    cleaned_files = 0

    while True:
        storage_paths = storage_query.values_list(model_field_name, flat=True)[
            :MANUAL_QUERY_BATCHSIZE
        ]
        cleaned_this_batch = cleanup_files_batched(context, storage_paths)
        cleaned_files += cleaned_this_batch

        cleaned_this_batch, _ = storage_query[:MANUAL_QUERY_BATCHSIZE].delete()

        if cleaned_this_batch == 0 or cleaned_this_batch == MANUAL_QUERY_BATCHSIZE:
            break

    return (cleaned_models, cleaned_files)


def cleanup_commitreport(context: CleanupContext, query: QuerySet) -> tuple[int, int]:
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


def cleanup_upload(context: CleanupContext, query: QuerySet) -> tuple[int, int]:
    storage_query = query.values_list("storage_path", flat=True)

    storage = StorageService()
    bucket = get_config("services", "minio", "bucket", default="archive")
    cleaned_files = 0
    # TODO: possibly fan out the batches to a thread pool, as the storage requests are IO-bound
    # TODO: do a limit / range query to avoid loading *all* the paths into memory at once
    for batched_paths in itertools.batched(storage_query, DELETE_FILES_BATCHSIZE):
        storage.delete_files(bucket, batched_paths)
        cleaned_files += len(batched_paths)

    cleaned_models, _ = query.delete()

    return (cleaned_models, cleaned_files)


# All the models that need custom python code for deletions so a bulk `DELETE` query does not work.
MANUAL_CLEANUP: dict[
    type[Model], Callable[[CleanupContext, QuerySet], tuple[int, int]]
] = {
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
