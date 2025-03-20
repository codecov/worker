import dataclasses
from collections import defaultdict
from collections.abc import Callable
from functools import partial

import sentry_sdk
from django.db.models import Model, Q, QuerySet
from shared.bundle_analysis import StoragePaths
from shared.django_apps.compare.models import CommitComparison
from shared.django_apps.core.models import Commit, Pull, Repository
from shared.django_apps.profiling.models import ProfilingUpload
from shared.django_apps.reports.models import (
    CommitReport,
    DailyTestRollup,
    ReportDetails,
    TestInstance,
)
from shared.django_apps.reports.models import ReportSession as Upload
from shared.django_apps.staticanalysis.models import StaticAnalysisSingleFileSnapshot
from shared.django_apps.timeseries.models import Dataset, Measurement
from shared.storage.exceptions import FileNotInStorageError
from shared.timeseries.helpers import is_timeseries_enabled
from shared.utils.sessions import SessionType

from services.archive import ArchiveService, MinioEndpoints
from services.cleanup.relations import reverse_filter
from services.cleanup.utils import CleanupContext, CleanupResult

MANUAL_QUERY_CHUNKSIZE = 1_000
DELETE_FILES_BATCHSIZE = 50


@sentry_sdk.trace
def cleanup_files_batched(
    context: CleanupContext, buckets_paths: dict[str, list[str]]
) -> int:
    def delete_file(bucket_path: tuple[str, str]) -> bool:
        try:
            return context.storage.delete_file(bucket_path[0], bucket_path[1])
        except FileNotInStorageError:
            return False
        except Exception as e:
            sentry_sdk.capture_exception(e)
            return False

    iter = ((bucket, path) for bucket, paths in buckets_paths.items() for path in paths)
    results = context.threadpool.map(delete_file, iter)
    return sum(results)


@sentry_sdk.trace
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

    # delete all those files from storage in chunks
    storage_query = query.filter(**{f"{path_field}__isnull": False}).values_list(
        "pk", path_field
    )
    while True:
        storage_results = dict(storage_query[:MANUAL_QUERY_CHUNKSIZE])
        if len(storage_results) == 0:
            break

        cleaned_files += cleanup_files_batched(
            context, {context.default_bucket: list(storage_results.values())}
        )
        # go through `query.object` here, to avoid some duplicated subqueries
        cleaned_models += query.model.objects.filter(
            pk__in=storage_results.keys()
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


@sentry_sdk.trace
def cleanup_commitreport(context: CleanupContext, query: QuerySet) -> CleanupResult:
    coverage_reports = query.values_list(
        "pk",
        "report_type",
        "code",
        "external_id",
        "commit__commitid",
        "commit__repository__repoid",
        "commit__repository__author__service",
        "commit__repository__service_id",
    )

    cleaned_models = 0
    cleaned_files = 0
    repo_hashes: dict[int, str] = {}

    while True:
        reports = list(coverage_reports[:MANUAL_QUERY_CHUNKSIZE])
        if len(reports) == 0:
            break

        buckets_paths: dict[str, list[str]] = defaultdict(list)
        for (
            _pk,
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
        cleaned_models += query.model.objects.filter(
            pk__in=(r[0] for r in reports)
        )._raw_delete(query.db)

    return CleanupResult(cleaned_models, cleaned_files)


@sentry_sdk.trace
def cleanup_upload(context: CleanupContext, query: QuerySet) -> CleanupResult:
    cleaned_files = 0

    # delete `None` `storage_path`s or carryforwarded right away,
    # as those duplicate their parents `storage_path`.
    cleaned_models = query.filter(
        Q(storage_path__isnull=True) | Q(upload_type=SessionType.carriedforward.value)
    )._raw_delete(query.db)

    # delete all those files from storage in chunks
    upload_query = query.filter(storage_path__isnull=False).values_list(
        "pk", "report__report_type", "storage_path"
    )
    while True:
        uploads = list(upload_query[:MANUAL_QUERY_CHUNKSIZE])
        if len(uploads) == 0:
            break

        buckets_paths: dict[str, list[str]] = defaultdict(list)
        for _pk, report_type, storage_path in uploads:
            if report_type == "bundle_analysis":
                buckets_paths[context.bundleanalysis_bucket].append(storage_path)
            else:
                buckets_paths[context.default_bucket].append(storage_path)

        cleaned_files += cleanup_files_batched(context, buckets_paths)
        cleaned_models += query.model.objects.filter(
            pk__in=(u[0] for u in uploads)
        )._raw_delete(query.db)

    return CleanupResult(cleaned_models, cleaned_files)


def cleanup_repository(context: CleanupContext, query: QuerySet) -> CleanupResult:
    # The equivalent of `SET NULL`:
    Repository.objects.filter(fork__in=query).update(fork=None)

    # Cleans up all the `timeseries` stuff:
    if is_timeseries_enabled():
        by_owner: dict[int, list[int]] = defaultdict(list)
        all_repo_ids: list[int] = []
        for owner_id, repo_id in query.values_list("author_id", "repoid"):
            by_owner[owner_id].append(repo_id)
            all_repo_ids.append(repo_id)

        datasets = Dataset.objects.filter(repository_id__in=all_repo_ids)
        datasets._for_write = True
        datasets._raw_delete(datasets.db)
        for owner_id, repo_ids in by_owner.items():
            measurements = Measurement.objects.filter(
                owner_id=owner_id,
                repo_id__in=repo_ids,
            )
            measurements._for_write = True
            measurements._raw_delete(measurements.db)

    return CleanupResult(query._raw_delete(query.db))


def unroll_subquery(context: CleanupContext, query: QuerySet) -> CleanupResult:
    reversed_query = reverse_filter(query)
    if not reversed_query:
        return CleanupResult(query._raw_delete(query.db))
    field, subquery = reversed_query

    cleaned_models = 0
    for parent in subquery:
        cleaned_models += query.model.objects.filter(**{field: parent.pk})._raw_delete(
            query.db
        )

    return CleanupResult(cleaned_models)


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
    Repository: cleanup_repository,
    TestInstance: unroll_subquery,
    DailyTestRollup: unroll_subquery,
}
