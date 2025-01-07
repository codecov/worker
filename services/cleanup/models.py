import dataclasses
import itertools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from django.db.models import Model
from django.db.models.query import Q, QuerySet
from shared.django_apps.core.models import Commit, Pull
from shared.django_apps.reports.models import CommitReport, ReportDetails, ReportSession

from services.archive import ArchiveService, MinioEndpoints
from services.cleanup.utils import CleanupContext

MANUAL_QUERY_CHUNKSIZE = 2_500
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
    cleaned_models = query.filter(**{f"{model_field_name}__isnull": True})._raw_delete(
        query.db
    )

    # and then delete all non-`None` `field_name`s:
    storage_query = query.filter(**{f"{model_field_name}__isnull": False})
    res = cleanup_with_storage_field(context, model_field_name, storage_query)

    cleaned_models += res[0]
    cleaned_files = res[1]
    return (cleaned_models, cleaned_files)


def cleanup_commitreport(context: CleanupContext, query: QuerySet) -> tuple[int, int]:
    coverage_reports = (
        query.filter(Q(report_type=None) | Q(report_type="coverage"))
        .values_list(
            "code",
            "commit__commitid",
            "repository__repoid",
            "repository__owner__service",
            "repository__service_id",
        )
        .order_by("id")
    )

    cleaned_models = 0
    cleaned_files = 0
    repo_hashes: dict[int, str] = {}

    while True:
        reports = coverage_reports[:MANUAL_QUERY_CHUNKSIZE]
        if len(reports) == 0:
            break

        storage_paths: list[str] = []
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
            storage_paths.append(path)

        cleaned_files += cleanup_files_batched(context, storage_paths)
        cleaned_models += query.filter(
            id__in=coverage_reports[:MANUAL_QUERY_CHUNKSIZE]
        )._raw_delete(query.db)

    return (cleaned_models, cleaned_files)


def cleanup_upload(context: CleanupContext, query: QuerySet) -> tuple[int, int]:
    return cleanup_with_storage_field(context, "storage_path", query)


def cleanup_with_storage_field(
    context: CleanupContext,
    path_field: str,
    query: QuerySet,
) -> tuple[int, int]:
    cleaned_models = 0
    cleaned_files = 0

    # delete all those files from storage, using chunks based on the `id` column
    storage_query = query.order_by("id")

    while True:
        storage_paths = storage_query.values_list(path_field, flat=True)[
            :MANUAL_QUERY_CHUNKSIZE
        ]
        if len(storage_paths) == 0:
            break

        cleaned_files += cleanup_files_batched(context, storage_paths)
        cleaned_models += query.filter(
            id__in=storage_query[:MANUAL_QUERY_CHUNKSIZE]
        )._raw_delete(query.db)

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
