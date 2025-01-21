import dataclasses
from collections import defaultdict
from collections.abc import Callable
from functools import partial

from django.db.models import Model
from django.db.models.query import QuerySet
from shared.bundle_analysis import StoragePaths
from shared.django_apps.compare.models import CommitComparison
from shared.django_apps.core.models import Commit, Pull
from shared.django_apps.profiling.models import ProfilingUpload
from shared.django_apps.reports.models import CommitReport, ReportDetails
from shared.django_apps.reports.models import ReportSession as Upload
from shared.django_apps.staticanalysis.models import StaticAnalysisSingleFileSnapshot

from services.archive import ArchiveService, MinioEndpoints
from services.cleanup.utils import CleanupContext, CleanupResult

MANUAL_QUERY_CHUNKSIZE = 5_000
DELETE_FILES_BATCHSIZE = 50


def cleanup_files_batched(
    context: CleanupContext, buckets_paths: dict[str, list[str]]
) -> int:
    def delete_file(bucket_path: tuple[str, str]) -> bool:
        return context.storage.delete_file(bucket_path[0], bucket_path[1])

    iter = ((bucket, path) for bucket, paths in buckets_paths.items() for path in paths)
    results = context.threadpool.map(delete_file, iter)
    return sum(results)


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

        cleaned_files += cleanup_files_batched(
            context, {context.default_bucket: storage_paths}
        )
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

        buckets_paths: dict[str, list[str]] = defaultdict(list)
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
            if report_type == "bundle_analysis":
                path = StoragePaths.bundle_report.path(
                    repo_key=repo_hash, report_key=external_id
                )
                buckets_paths[context.bundleanalysis_bucket].append(path)
            elif report_type == "test_results":
                # TA has cached rollups, but those are based on `Branch`
                pass
            else:
                chunks_file_name = report_code if report_code is not None else "chunks"
                path = MinioEndpoints.chunks.get_path(
                    version="v4",
                    repo_hash=repo_hash,
                    commitid=commit_sha,
                    chunks_file_name=chunks_file_name,
                )
                buckets_paths[context.default_bucket].append(path)

        cleaned_files += cleanup_files_batched(context, buckets_paths)
        cleaned_models += query.filter(
            id__in=query.order_by("id")[:MANUAL_QUERY_CHUNKSIZE]
        )._raw_delete(query.db)

    return CleanupResult(cleaned_models, cleaned_files)


def cleanup_upload(context: CleanupContext, query: QuerySet) -> CleanupResult:
    cleaned_files = 0

    # delete `None` `storage_path`s right away
    cleaned_models = query.filter(storage_path__isnull=True)._raw_delete(query.db)

    # delete all those files from storage, using chunks based on the `id` column
    storage_query = query.filter(storage_path__isnull=False).order_by("id")

    while True:
        uploads = storage_query.values_list("report__report_type", "storage_path")[
            :MANUAL_QUERY_CHUNKSIZE
        ]
        if len(uploads) == 0:
            break

        buckets_paths: dict[str, list[str]] = defaultdict(list)
        for report_type, storage_path in uploads:
            if report_type == "bundle_analysis":
                buckets_paths[context.bundleanalysis_bucket].append(storage_path)
            else:
                buckets_paths[context.default_bucket].append(storage_path)

        cleaned_files += cleanup_files_batched(context, buckets_paths)
        cleaned_models += query.filter(
            id__in=storage_query[:MANUAL_QUERY_CHUNKSIZE]
        )._raw_delete(query.db)

    return CleanupResult(cleaned_models, cleaned_files)


# All the models that need custom python code for deletions so a bulk `DELETE` query does not work.
MANUAL_CLEANUP: dict[
    type[Model], Callable[[CleanupContext, QuerySet], CleanupResult]
] = {
    Commit: partial(cleanup_archivefield, "report"),
    Pull: partial(cleanup_archivefield, "flare"),
    ReportDetails: partial(cleanup_archivefield, "files_array"),
    CommitReport: cleanup_commitreport,
    Upload: cleanup_upload,
    CommitComparison: partial(cleanup_with_storage_field, "report_storage_path"),
    ProfilingUpload: partial(cleanup_with_storage_field, "raw_upload_location"),
    StaticAnalysisSingleFileSnapshot: partial(
        cleanup_with_storage_field, "content_location"
    ),
}
