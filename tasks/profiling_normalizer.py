import dataclasses
import json
import logging
from base64 import b64decode
from typing import Dict

from shared.celery_config import profiling_normalization_task_name
from shared.storage.exceptions import FileNotInStorageError
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.profiling import ProfilingUpload
from helpers.clock import get_utc_now
from services.archive import ArchiveService
from services.path_fixer import PathFixer
from services.report.parser.types import ParsedUploadedReportFile
from services.report.report_builder import ReportBuilder
from services.report.report_processor import process_report
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ProfilingNormalizerTask(BaseCodecovTask, name=profiling_normalization_task_name):
    def run_impl(self, db_session: Session, *, profiling_upload_id: int, **kwargs):
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
        runs = []
        number_spans = 0
        files_dict = {}
        for element in data["spans"]:
            if "codecov" in element and "coverage" in element["codecov"]:
                number_spans += 1
                report_file_upload = ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b64decode(element["codecov"]["coverage"]),
                )
                path_fixer = PathFixer.init_from_user_yaml(
                    current_yaml,
                    [],
                    [],
                    extra_fixes=current_yaml.read_yaml_field("profiling", "fixes")
                    or [],
                )
                report = process_report(
                    report_file_upload,
                    report_builder=ReportBuilder(current_yaml, 1, {}, path_fixer),
                )
                runs.append(
                    self._extract_report_into_dict(
                        current_yaml,
                        report,
                        element["span"] if "span" in element else element,
                        files_dict,
                    )
                )
        for name in files_dict:
            files_dict[name]["executable_lines"] = sorted(
                files_dict[name]["executable_lines"]
            )
        return {"runs": runs, "files": files_dict}

    def _extract_report_into_dict(self, current_yaml, report, element, files_dict):
        relevant_attributes = sorted(
            current_yaml.get("profiling", {}).get("grouping_attributes", [])
        )
        into_dict = {
            "grouping_attributes": [
                (key, element["attributes"].get(key)) for key in relevant_attributes
            ],
            "group": element["name"],
            "execs": [],
        }
        for filename in report.files:
            file_dict = files_dict.setdefault(filename, {"executable_lines": set()})
            file_report = report.get(filename)
            into_file_dict = {"filename": filename, "lines": []}
            into_dict["execs"].append(into_file_dict)
            for line_number, line in file_report.lines:
                (
                    coverage,
                    line_type,
                    sessions,
                    messages,
                    complexity,
                    datapoints,
                ) = dataclasses.astuple(line)
                # TODO: Make this next lines more resilient
                line_count = (
                    coverage
                    if coverage and isinstance(coverage, int)
                    else int(coverage)
                )
                file_dict["executable_lines"].add(line_number)
                if line_count > 0:
                    into_file_dict["lines"].append((line_number, line_count))
        return into_dict

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
