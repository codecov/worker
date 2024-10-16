from dataclasses import dataclass

import sentry_sdk
from shared.reports.editable import EditableReport, EditableReportFile
from shared.reports.enums import UploadState
from shared.reports.resources import Report
from shared.yaml import UserYaml
from sqlalchemy.orm import Session as DbSession

from database.models.reports import Upload
from services.processing.loading import IntermediateReport
from services.report import delete_uploads_by_sessionid
from services.report.raw_upload_processor import clear_carryforward_sessions


@dataclass
class MergeResult:
    session_mapping: dict[int, int]
    """
    This is a mapping from the input `upload_id` to the output `session_id`
    as it exists in the merged "master Report".
    """

    deleted_sessions: set[int]
    """
    The Set of carryforwarded `session_id`s that have been removed from the "master Report".
    """


@sentry_sdk.trace
def merge_reports(
    commit_yaml: UserYaml,
    master_report: Report,
    intermediate_reports: list[IntermediateReport],
) -> MergeResult:
    session_mapping: dict[int, int] = dict()
    deleted_sessions: set[int] = set()

    for intermediate_report in intermediate_reports:
        report = intermediate_report.report
        if report.is_empty():
            continue

        old_sessionid = next(iter(report.sessions))
        new_sessionid = master_report.next_session_number()
        change_sessionid(report, old_sessionid, new_sessionid)
        session_mapping[intermediate_report.upload_id] = new_sessionid

        session = report.sessions[new_sessionid]

        _session_id, session = master_report.add_session(
            session, use_id_from_session=True
        )

        if flags := session.flags:
            session_adjustment = clear_carryforward_sessions(
                master_report, report, flags, commit_yaml
            )
            deleted_sessions.update(session_adjustment.fully_deleted_sessions)

        master_report.merge(report)

    return MergeResult(session_mapping, deleted_sessions)


@sentry_sdk.trace
def update_uploads(db_session: DbSession, merge_result: MergeResult):
    """
    Updates all the `Upload` records with the `MergeResult`.
    In particular, this updates the `order_number` to match the new `session_id`,
    and it deletes all the `Upload` records matching removed carry-forwarded `Session`s.
    """

    # first, delete removed sessions, as report merging can reuse deleted `session_id`s.
    if merge_result.deleted_sessions:
        any_upload_id = next(iter(merge_result.session_mapping.keys()))
        report_id = (
            db_session.query(Upload.report_id)
            .filter(Upload.id_ == any_upload_id)
            .first()[0]
        )

        delete_uploads_by_sessionid(
            db_session, report_id, merge_result.deleted_sessions
        )

    # then, update all the sessions that have been merged
    for upload_id, session_id in merge_result.session_mapping.items():
        update = {
            Upload.state_id: UploadState.PROCESSED.db_id,
            Upload.state: "processed",
            Upload.order_number: session_id,
        }
        db_session.query(Upload).filter(Upload.id_ == upload_id).update(update)
    db_session.flush()


def change_sessionid(report: EditableReport, old_id: int, new_id: int):
    """
    Modifies the `EditableReport`, changing the session with `old_id` to have `new_id` instead.
    This patches up all the references to that session across all files and line records.

    In particular, it changes the id in all the `LineSession`s and `CoverageDatapoint`s,
    and does the equivalent of `calculate_present_sessions`.
    """
    session = report.sessions[new_id] = report.sessions.pop(old_id)
    session.id = new_id

    report_file: EditableReportFile
    for report_file in report._chunks:
        if report_file is None:
            continue

        all_sessions = set()

        for idx, _line in enumerate(report_file._lines):
            if not _line:
                continue

            # this turns the line into an actual `ReportLine`
            line = report_file._lines[idx] = report_file._line(_line)

            for session in line.sessions:
                if session.id == old_id:
                    session.id = new_id
                all_sessions.add(session.id)

            if line.datapoints:
                for point in line.datapoints:
                    if point.sessionid == old_id:
                        point.sessionid = new_id

        report_file._details["present_sessions"] = all_sessions
