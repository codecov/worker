import logging
from typing import Mapping, Any, Optional

from shared.reports.resources import Report
from shared.reports.editable import EditableReport
from shared.storage.exceptions import FileNotInStorageError
from shared.reports.carryforward import generate_carryforward_report

from database.models import Commit
from services.archive import ArchiveService
from services.report.raw_upload_processor import process_raw_upload
from services.yaml.reader import read_yaml_field, get_paths_from_flags

log = logging.getLogger(__name__)


class NotReadyToBuildReportYetError(Exception):
    pass


class ReportService(object):
    def __init__(self, current_yaml: Mapping[str, Any] = None):
        self.current_yaml = current_yaml

    def build_report(self, chunks, files, sessions, totals) -> Report:
        report_class = Report
        for sess in sessions.values():
            if sess.get("st") == "carriedforward":
                report_class = EditableReport
        return report_class(
            chunks=chunks, files=files, sessions=sessions, totals=totals
        )

    def build_report_from_commit(self, commit) -> Report:
        return self._do_build_report_from_commit(commit)

    def get_existing_report_for_commit(self, commit) -> Optional[Report]:
        commitid = commit.commitid
        if commit.report_json is None:
            return None
        try:
            chunks_archive_service = ArchiveService(commit.repository)
            chunks = chunks_archive_service.read_chunks(commitid)
        except FileNotInStorageError:
            log.warning(
                "File for chunks not found in storage",
                extra=dict(commit=commitid, repo=commit.repoid),
            )
            return None
        if chunks is None:
            return None
        files = commit.report_json["files"]
        sessions = commit.report_json["sessions"]
        totals = commit.totals
        res = self.build_report(chunks, files, sessions, totals)
        return res

    def _do_build_report_from_commit(self, commit) -> Report:
        report = self.get_existing_report_for_commit(commit)
        if report is not None:
            return report
        return self.create_new_report_for_commit(commit)

    def get_appropriate_commit_to_carryforward_from(
        self, commit: Commit
    ) -> Optional[Commit]:
        parent_commit = commit.get_parent_commit()
        max_parenthood_deepness = 10
        parent_commit_tracking = []
        count = 1  # `parent_commit` is already the first parent
        while (
            parent_commit is not None
            and parent_commit.state not in ("complete", "skipped")
            and count < max_parenthood_deepness
        ):
            parent_commit_tracking.append(parent_commit.commitid)
            if (
                parent_commit.state == "pending"
                and parent_commit.parent_commit_id is None
            ):
                log.warning(
                    "One of the ancestors commit doesn't seem to have determined its parent yet",
                    extra=dict(
                        commit=commit.commitid,
                        repoid=commit.repoid,
                        current_parent_commit=parent_commit.commitid,
                    ),
                )
                raise NotReadyToBuildReportYetError()
            log.info(
                "Going from parent to their parent since they dont match the requisites for CFF",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    current_parent_commit=parent_commit.commitid,
                    parent_tracking=parent_commit_tracking,
                    current_state=parent_commit.state,
                    new_parent_commit=parent_commit.parent_commit_id,
                ),
            )
            parent_commit = parent_commit.get_parent_commit()
            count += 1
        if parent_commit is None:
            log.warning(
                "No parent commit was found to be carriedforward from",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    parent_tracing=parent_commit_tracking,
                ),
            )
            return None
        if parent_commit.state not in ("complete", "skipped"):
            log.warning(
                "None of the parent commits were in a complete state to be used as CFing base",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    parent_tracking=parent_commit_tracking,
                    would_be_state=parent_commit.state,
                    would_be_parent=parent_commit.commitid,
                ),
            )
            return None
        return parent_commit

    def create_new_report_for_commit(self, commit: Commit) -> Report:
        log.info(
            "Creating new report for commit",
            extra=dict(commit=commit.commitid, repoid=commit.repoid,),
        )
        if not self.current_yaml:
            return Report()
        flags_to_carryforward = []
        all_flags = read_yaml_field(self.current_yaml, ("flags",))
        if all_flags:
            for flag_name, flag_info in all_flags.items():
                if flag_info.get("carryforward"):
                    flags_to_carryforward.append(flag_name)
        if not flags_to_carryforward:
            return Report()
        log.info(
            "Flags were found to be carriedforward",
            extra=dict(
                commit=commit.commitid,
                repoid=commit.repoid,
                flags_to_carryforward=flags_to_carryforward,
            ),
        )
        paths_to_carryforward = get_paths_from_flags(
            self.current_yaml, flags_to_carryforward
        )
        parent_commit = self.get_appropriate_commit_to_carryforward_from(commit)
        if parent_commit is None:
            log.warning(
                "Could not carryforward report from another commit despite having CF flags",
                extra=dict(
                    commit=commit.commitid,
                    repoid=commit.repoid,
                    some_flags_to_carryforward=flags_to_carryforward[:100],
                ),
            )
            return Report()
        parent_report = self.get_existing_report_for_commit(parent_commit)
        log.info(
            "Generating carriedforward report",
            extra=dict(
                commit=commit.commitid,
                repoid=commit.repoid,
                parent_commit=parent_commit.commitid,
                flags_to_carryforward=flags_to_carryforward,
                paths_to_carryforward=paths_to_carryforward,
                parent_sessions=parent_report.sessions,
            ),
        )
        return generate_carryforward_report(
            parent_report,
            flags_to_carryforward,
            paths_to_carryforward,
            session_extras=dict(carryforwardorwarded_from=parent_commit.commitid),
        )

    def build_report_from_raw_content(
        self, commit_yaml, master, reports, flags, session
    ) -> Any:
        return process_raw_upload(commit_yaml, master, reports, flags, session)
