import dataclasses
import itertools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from django.db.models import Model
from django.db.models.query import QuerySet
from shared.bundle_analysis import StoragePaths
from shared.django_apps.compare.models import CommitComparison
from shared.django_apps.core.models import Commit, Pull
from shared.django_apps.reports.models import CommitReport, ReportDetails
from shared.django_apps.reports.models import ReportSession as Upload

from services.archive import ArchiveService, MinioEndpoints
from services.cleanup.utils import CleanupContext, CleanupResult

MANUAL_QUERY_CHUNKSIZE = 2_500
DELETE_FILES_BATCHSIZE = 50


def cleanup_files_batched(context: CleanupContext, paths: list[str]) -> int:
    cleaned_files = 0

    # TODO: maybe reuse the executor across calls?
    with ThreadPoolExecutor() as e:
        for batched_paths in itertools.batched(paths, DELETE_FILES_BATCHSIZE):
            e.submit(context.storage.delete_files, context.bucket, list(batched_paths))

        cleaned_files += len(batched_paths)

    return cleaned_files


def cleanup_with_storage_field(
    path_field: str,
    context: CleanupContext,
    query: QuerySet,
) -> CleanupResult:
    cleaned_files = 0

    # delete `None` `path_field`s right away
    cleaned_models = query.filter(**{f"{path_field}__isnull": True})._raw_delete(
        query.db
    )

    # delete all those files from storage, using chunks based on the `id` column
    storage_query = query.filter(**{f"{path_field}__isnull": False}).order_by("id")

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

    return CleanupResult(cleaned_models, cleaned_files)


def cleanup_archivefield(
    field_name: str, context: CleanupContext, query: QuerySet
) -> CleanupResult:
    model_field_name = f"_{field_name}_storage_path"

    return cleanup_with_storage_field(model_field_name, context, query)


# This has all the `Repository` fields needed by `get_archive_hash`
@dataclasses.dataclass
class FakeRepository:
    repoid: int
    service: str
    service_id: str


def cleanup_commitreport(context: CleanupContext, query: QuerySet) -> CleanupResult:
    coverage_reports = query.values_list(
        "report_type",
        "code",
        "external_id",
        "commit__commitid",
        "commit__repository__repoid",
        "commit__repository__author__service",
        "commit__repository__service_id",
    ).order_by("id")

    cleaned_models = 0
    cleaned_files = 0
    repo_hashes: dict[int, str] = {}

    while True:
        reports = coverage_reports[:MANUAL_QUERY_CHUNKSIZE]
        if len(reports) == 0:
            break

        storage_paths: list[str] = []
        for (
            report_type,
            report_code,
            external_id,
            commit_sha,
            repoid,
            repo_service,
            repo_service_id,
        ) in reports:
            if repoid not in repo_hashes:
                fake_repo = FakeRepository(
                    repoid=repoid, service=repo_service, service_id=repo_service_id
                )
                repo_hashes[repoid] = ArchiveService.get_archive_hash(fake_repo)
            repo_hash = repo_hashes[repoid]

            # depending on the `report_type`, we have:
            # - a `chunks` file for coverage
            # - a `bundle_report.sqlite` for BA
            match report_type:
                case "bundle_analysis":
                    path = StoragePaths.bundle_report.path(
                        repo_key=repo_hash, report_key=external_id
                    )
                    # TODO: bundle analysis lives in a different bucket I believe?
                    storage_paths.append(path)
                case "test_results":
                    # TODO:
                    pass
                case _:  # coverage
                    chunks_file_name = (
                        report_code if report_code is not None else "chunks"
                    )
                    path = MinioEndpoints.chunks.get_path(
                        version="v4",
                        repo_hash=repo_hash,
                        commitid=commit_sha,
                        chunks_file_name=chunks_file_name,
                    )
                    storage_paths.append(path)

        cleaned_files += cleanup_files_batched(context, storage_paths)
        cleaned_models += query.filter(
            id__in=query.order_by("id")[:MANUAL_QUERY_CHUNKSIZE]
        )._raw_delete(query.db)

    return CleanupResult(cleaned_models, cleaned_files)


# "v1/repos/{repo_key}/{report_key}/bundle_report.sqlite"


# All the models that need custom python code for deletions so a bulk `DELETE` query does not work.
MANUAL_CLEANUP: dict[
    type[Model], Callable[[CleanupContext, QuerySet], CleanupResult]
] = {
    Commit: partial(cleanup_archivefield, "report"),
    Pull: partial(cleanup_archivefield, "flare"),
    ReportDetails: partial(cleanup_archivefield, "files_array"),
    CommitReport: cleanup_commitreport,
    Upload: partial(cleanup_with_storage_field, "storage_path"),
    CommitComparison: partial(cleanup_with_storage_field, "report_storage_path"),
    # TODO: figure out any other models which have files in storage that are not `ArchiveField`
    # TODO: TA is also storing files in GCS
    # TODO: profiling, label analysis and static analysis also needs porting to django
}
