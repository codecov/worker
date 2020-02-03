import logging
from typing import Mapping, Any

from covreports.reports.resources import Report
from covreports.reports.editable import EditableReport
from covreports.storage.exceptions import FileNotInStorageError
from covreports.reports.carryforward import generate_carryforward_report

from database.models import Commit
from services.archive import ArchiveService
from services.report.raw_upload_processor import process_raw_upload
from services.yaml.reader import read_yaml_field

log = logging.getLogger(__name__)


class ReportService(object):

    def __init__(self, current_yaml: Mapping[str, Any] = None):
        self.current_yaml = current_yaml

    def build_report(self, chunks, files, sessions, totals):
        return EditableReport(chunks=chunks, files=files, sessions=sessions, totals=totals)

    def build_report_from_commit(self, commit):
        return self._do_build_report_from_commit(commit, recursion_limit=1)

    def _do_build_report_from_commit(self, commit, recursion_limit):
        commitid = commit.commitid
        if commit.report_json is None:
            return self.create_new_report_for_commit(commit, recursion_limit)
        try:
            chunks_archive_service = ArchiveService(commit.repository)
            chunks = chunks_archive_service.read_chunks(commitid)
        except FileNotInStorageError:
            log.warning(
                "File for chunks not found in storage",
                extra=dict(
                    commit=commitid,
                    repo=commit.repoid
                )
            )
            return self.create_new_report_for_commit(commit, recursion_limit)
        if chunks is None:
            return self.create_new_report_for_commit(commit, recursion_limit)
        files = commit.report_json['files']
        sessions = commit.report_json['sessions']
        totals = commit.totals
        res = self.build_report(chunks, files, sessions, totals)
        return res

    def create_new_report_for_commit(self, commit: Commit, recursion_limit=0):
        if not self.current_yaml:
            return Report()
        if recursion_limit <= 0:
            return Report()
        flags_to_carryforward = []
        flags = read_yaml_field(self.current_yaml, ('flags', ))
        if flags:
            for flag_name, flag_info in flags.items():
                if flag_info.get('carryforward'):
                    flags_to_carryforward.append(flag_name)
        parent_commit = commit.get_parent_commit()
        if parent_commit is None:
            return Report()
        parent_report = self._do_build_report_from_commit(parent_commit, recursion_limit - 1)
        return generate_carryforward_report(parent_report, flags_to_carryforward)

    def build_report_from_raw_content(self, commit_yaml, master, reports, flags, session):
        return process_raw_upload(commit_yaml, master, reports, flags, session)
