import json
import logging

from covreports.resources import Report
from services.archive import ArchiveService, MinioEndpoints
from services.report.raw_upload_processor import process_raw_upload
from services.storage.exceptions import FileNotInStorageError

log = logging.getLogger(__name__)


class ReportService(object):

    def build_report(self, chunks, files, sessions, totals):
        return Report(chunks=chunks, files=files, sessions=sessions, totals=totals)

    def build_report_from_commit(self, commit, chunks_archive_service=None):
        commitid = commit.commitid
        if commit.report_json is None:
            return Report(totals=None, chunks=None)
        try:
            if chunks_archive_service is None:
                chunks_archive_service = ArchiveService(commit.repository)
            chunks = chunks_archive_service.read_chunks(commitid)
        except FileNotInStorageError:
            return Report(totals=None, chunks=None)
        if chunks is None:
            return Report(totals=None, chunks=None)
        # TODO: Remove after tests are done
        try:
            actual_reports_path = MinioEndpoints.reports_json.get_path(
                version='v4',
                repo_hash=chunks_archive_service.storage_hash,
                commitid=commitid
            )
            report_dict = json.loads(chunks_archive_service.read_file(actual_reports_path))
            files = report_dict['files']
            sessions = report_dict['sessions']
        except (FileNotInStorageError, json.decoder.JSONDecodeError):
            log.exception(
                "What happened in here?", extra=dict(actual_reports_path=actual_reports_path)
            )
            files = commit.report_json['files']
            sessions = commit.report_json['sessions']
        totals = commit.totals
        res = self.build_report(chunks, files, sessions, totals)
        return res

    def build_report_from_raw_content(self, commit_yaml, master, reports, flags, session):
        return process_raw_upload(commit_yaml, master, reports, flags, session)
