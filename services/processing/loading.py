import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import sentry_sdk
from shared.reports.editable import EditableReport

from services.archive import ArchiveService
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
        # TODO: migrate these files to a better storage location
        prefix = f"v4/repos/{repo_hash}/commits/{commitsha}/parallel/incremental"
        chunks_path = f"{prefix}/chunk{upload_id}.txt"
        json_path = f"{prefix}/files_and_sessions{upload_id}.txt"

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
