import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import sentry_sdk
from shared.reports.editable import EditableReport

from services.archive import ArchiveService, MinioEndpoints
from services.processing.state import MERGE_BATCH_SIZE


@dataclass
class IntermediateReport:
    upload_id: int
    """
    The `Upload` id for which this report was loaded.
    """

    report: EditableReport
    """
    The loaded Report.
    """


@sentry_sdk.trace
def load_intermediate_reports(
    archive_service: ArchiveService,
    commitsha: str,
    upload_ids: list[int],
) -> list[IntermediateReport]:
    def load_report(upload_id: int) -> IntermediateReport:
        repo_hash = archive_service.storage_hash
        json_path, chunks_path = intermediate_report_paths(
            repo_hash, commitsha, upload_id
        )

        chunks = archive_service.read_file(chunks_path).decode(errors="replace")
        report_json = json.loads(archive_service.read_file(json_path))

        report = EditableReport.from_chunks(
            chunks=chunks,
            files=report_json["files"],
            sessions=report_json["sessions"],
            totals=report_json.get("totals"),
        )
        return IntermediateReport(upload_id, report)

    with ThreadPoolExecutor(max_workers=MERGE_BATCH_SIZE) as pool:
        loaded_reports = pool.map(load_report, upload_ids)
        return list(loaded_reports)


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

    # there are only relevant for the "experiment" mode:
    files_to_delete = list(experiment_report_paths(repo_hash, commitsha))

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


def experiment_report_paths(repo_hash: str, commitsha: str) -> tuple[str, str]:
    return MinioEndpoints.parallel_upload_experiment.get_path(
        version="v4",
        repo_hash=repo_hash,
        commitid=commitsha,
        file_name="files_and_sessions",
    ), MinioEndpoints.parallel_upload_experiment.get_path(
        version="v4",
        repo_hash=repo_hash,
        commitid=commitsha,
        file_name="chunks",
    )
