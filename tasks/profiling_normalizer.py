import dataclasses
import json
import logging
from io import BytesIO
from typing import Dict, List

from shared.storage.exceptions import FileNotInStorageError
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.profiling import ProfilingUpload
from helpers.clock import get_utc_now
from services.archive import ArchiveService
from services.report.parser import ParsedUploadedReportFile
from services.report.report_processor import process_report
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ProfilingNormalizerTask(BaseCodecovTask):

    name = "app.tasks.profilingnormalizertask"

    async def run_async(
        self, db_session: Session, *, profiling_upload_id: int, **kwargs,
    ):
        profiling_upload = (
            db_session.query(ProfilingUpload).filter_by(id=profiling_upload_id).first()
        )
        log.info(
            "Fetching data from profiling",
            extra=dict(location=profiling_upload.raw_upload_location),
        )
        try:
            data = json.loads(
                ArchiveService(profiling_upload.profiling_commit.repository).read_file(
                    profiling_upload.raw_upload_location
                )
            )
        except FileNotInStorageError:
            log.info(
                "Could not find data for normalization of profiling",
                extra=dict(profiling_upload_id=profiling_upload_id),
            )
            return {"successful": False}
        current_yaml = get_repo_yaml(profiling_upload.profiling_commit.repository)
        dict_to_store = self.normalize_data(current_yaml, data)
        location = None
        if dict_to_store.get("files"):
            location = self.store_normalization_results(profiling_upload, dict_to_store)
            log.info("Stored normalized results", extra=dict(location=location))
        return {"successful": True, "location": location}

    def normalize_data(self, current_yaml, data: Dict) -> Dict:
        """Normalizes from codecov-opentelemetry format into the format we used initially

        The data format is a dict that contains a key (span) that is an array
            of opentelemetry spans:
            {
                "name": "HTTP GET",
                "context": {
                    "trace_id": "0x7b3455791d6db8591e3c5fc64c4ad2c6",
                    "span_id": "0xb1e9e5dfc7398780",
                    "trace_state": "[]"
                },
                "kind": "SpanKind.SERVER",
                "parent_id": null,
                "start_time": "2021-08-11T23:22:23.255281Z",
                "end_time": "2021-08-11T23:22:23.263379Z",
                "status": {
                    "status_code": "UNSET"
                },
                "attributes": {
                    "http.method": "GET",
                    "http.server_name": "0.0.0.0",
                    "http.scheme": "http",
                    "net.host.port": 8000,
                    "http.host": "api.localhost",
                    "http.target": "/static/admin/css/changelists.css",
                    "net.peer.ip": "172.19.0.10",
                    "http.user_agent": "Mozilla/5.0 ...Firefox/91.0",
                    "net.peer.port": "50120",
                    "http.flavor": "1.1",
                    "http.status_code": 304
                },
                "events": [],
                "links": [],
                "resource": {
                    "telemetry.sdk.language": "python",
                    "telemetry.sdk.name": "opentelemetry",
                    "telemetry.sdk.version": "1.3.0",
                    "service.name": "unknown_service"
                },
                "coverage": "<?xml version=\"1.0\" ?>\n<coverage branch-rate=\"0\" ...</packages>\n</coverage>\n"
            }

        Args:
            data (List[Dict]): Description

        Returns:
            Dict: Description
        """
        res = {}
        for element in data["spans"]:
            if "coverage" in element:
                report_file_upload = ParsedUploadedReportFile(
                    filename=None, file_contents=BytesIO(element["coverage"].encode())
                )
                report = process_report(
                    report_file_upload, current_yaml, 1, {}, lambda x, bases_to_try: x
                )
                if report:
                    self._extract_report_into_dict(report, res)
        return {"files": res}

    def _extract_report_into_dict(self, report, into_dict):
        for filename in report.files:
            file_dict = into_dict.setdefault(filename, {})
            file_report = report.get(filename)
            for line_number, line in file_report.lines:
                (
                    coverage,
                    line_type,
                    sessions,
                    messages,
                    complexity,
                ) = dataclasses.astuple(line)
                # TODO: Make this next lines more resilient
                line_count = (
                    coverage
                    if coverage and isinstance(coverage, int)
                    else int(coverage)
                )
                if line_number not in file_dict:
                    file_dict[line_number] = 0
                file_dict[line_number] += line_count

    def store_normalization_results(self, profiling: ProfilingUpload, results):
        archive_service = ArchiveService(profiling.profiling_commit.repository)
        location = archive_service.write_profiling_normalization_result(
            profiling.profiling_commit.version_identifier, json.dumps(results)
        )
        profiling.normalized_location = location
        profiling.normalized_at = get_utc_now()
        return location


RegisteredProfilingNormalizerTask = celery_app.register_task(ProfilingNormalizerTask())
profiling_normalizer_task = celery_app.tasks[RegisteredProfilingNormalizerTask.name]
