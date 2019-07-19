import minio

from covreports.resources import Report
from services.archive import ArchiveService
from services.report.raw_upload_processor import process_raw_upload


class ReportService(object):

    def build_report(self, chunks, files, sessions, totals):
        return Report(chunks=chunks, files=files, sessions=sessions, totals=totals)

    def build_report_from_commit(self, commit):
        commitid = commit.commitid
        if commit.report is None:
            return Report(totals=None, chunks=None)
        try:
            chunks = ArchiveService(commit.repository).read_chunks(commitid)
        except minio.error.NoSuchKey:
            return Report(totals=None, chunks=None)
        if chunks is None:
            return Report(totals=None, chunks=None)
        files = commit.report['files']
        sessions = commit.report['sessions']
        totals = commit.totals
        res = self.build_report(chunks, files, sessions, totals)
        return res

    def build_report_from_raw_content(self, repository, master, reports, flags, session):
        return process_raw_upload(repository, master, reports, flags, session)
