from concurrent.futures import ThreadPoolExecutor

import orjson
import sentry_sdk
import zstandard
from shared.reports.editable import EditableReport
from shared.reports.resources import Report

from services.archive import ArchiveService

from .metrics import INTERMEDIATE_REPORT_SIZE
from .types import IntermediateReport


@sentry_sdk.trace
def load_intermediate_reports(
    archive_service: ArchiveService,
    commitsha: str,
    upload_ids: list[int],
) -> list[IntermediateReport]:
    @sentry_sdk.trace
    def load_report(upload_id: int) -> IntermediateReport:
        repo_hash = archive_service.storage_hash
        json_path, chunks_path = intermediate_report_paths(
            repo_hash, commitsha, upload_id
        )

        chunks = archive_service.read_file(chunks_path).decode(errors="replace")
        report_json = orjson.loads(archive_service.read_file(json_path))

        report = EditableReport.from_chunks(
            chunks=chunks,
            files=report_json["files"],
            sessions=report_json["sessions"],
            totals=report_json.get("totals"),
        )
        return IntermediateReport(upload_id, report)

    def instrumented_load_report(upload_id: int) -> IntermediateReport:
        with sentry_sdk.isolation_scope() as _scope:
            return load_report(upload_id)

    with ThreadPoolExecutor() as pool:
        loaded_reports = pool.map(instrumented_load_report, upload_ids)
        return list(loaded_reports)


@sentry_sdk.trace
def save_intermediate_report(
    archive_service: ArchiveService,
    commitsha: str,
    upload_id: int,
    report: Report,
):
    _totals, report_json = report.to_database()
    report_json = report_json.encode()
    chunks = report.to_archive().encode()
    emit_size_metrics(report_json, chunks)

    repo_hash = archive_service.storage_hash
    json_path, chunks_path = intermediate_report_paths(repo_hash, commitsha, upload_id)

    archive_service.write_file(json_path, report_json)
    archive_service.write_file(chunks_path, chunks)


@sentry_sdk.trace
def cleanup_intermediate_reports(
    archive_service: ArchiveService,
    commitsha: str,
    upload_ids: list[int],
):
    """
    Cleans up the files in storage that contain the "intermediate Report"s
    from parallel processing, as well as the copy of the "master Report" used
    for the "experiment" mode.
    """
    repo_hash = archive_service.storage_hash

    files_to_delete: list[str] = []

    for upload_id in upload_ids:
        files_to_delete.extend(
            intermediate_report_paths(repo_hash, commitsha, upload_id)
        )

    archive_service.delete_files(files_to_delete)


def intermediate_report_paths(
    repo_hash: str, commitsha: str, upload_id: int
) -> tuple[str, str]:
    # TODO: migrate these files to a better storage location
    prefix = f"v4/repos/{repo_hash}/commits/{commitsha}/parallel/incremental"
    chunks_path = f"{prefix}/chunk{upload_id}.txt"
    json_path = f"{prefix}/files_and_sessions{upload_id}.txt"
    return json_path, chunks_path


def emit_size_metrics(report_json: bytes, chunks: bytes):
    INTERMEDIATE_REPORT_SIZE.labels(type="report_json", compression="none").observe(
        len(report_json)
    )
    INTERMEDIATE_REPORT_SIZE.labels(type="chunks", compression="none").observe(
        len(chunks)
    )
    INTERMEDIATE_REPORT_SIZE.labels(type="report_json", compression="zstd").observe(
        len(zstandard.compress(report_json))
    )
    INTERMEDIATE_REPORT_SIZE.labels(type="chunks", compression="zstd").observe(
        len(zstandard.compress(chunks))
    )
