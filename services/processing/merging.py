import functools
from decimal import Decimal

import sentry_sdk
from shared.reports.editable import EditableReport, EditableReportFile
from shared.reports.enums import UploadState
from shared.reports.resources import Report, ReportTotals
from shared.yaml import UserYaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from database.models.reports import Upload, UploadError, UploadLevelTotals
from helpers.number import precise_round
from services.report import delete_uploads_by_sessionid
from services.report.raw_upload_processor import clear_carryforward_sessions
from services.yaml.reader import read_yaml_field

from .types import IntermediateReport, MergeResult, ProcessingResult


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
def update_uploads(
    db_session: DbSession,
    commit_yaml: UserYaml,
    processing_results: list[ProcessingResult],
    intermediate_reports: list[IntermediateReport],
    merge_result: MergeResult,
):
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

    precision: int = read_yaml_field(commit_yaml, ("coverage", "precision"), 2)
    rounding: str = read_yaml_field(commit_yaml, ("coverage", "round"), "nearest")
    make_totals = functools.partial(make_upload_totals, precision, rounding)

    reports = {ir.upload_id: ir.report for ir in intermediate_reports}

    # then, update all the `Upload`s with their state, and the final `order_number`,
    # as well as add a `UploadLevelTotals` or `UploadError`s where appropriate.
    all_errors: list[UploadError] = []
    all_totals: list[dict] = []
    all_upload_updates: list[dict] = []
    for result in processing_results:
        upload_id = result["upload_id"]

        if result["successful"]:
            update = {
                "state_id": UploadState.PROCESSED.db_id,
                "state": "processed",
            }
            report = reports.get(upload_id)
            if report is not None:
                all_totals.append(make_totals(upload_id, report.totals))
        elif result["error"]:
            update = {
                "state_id": UploadState.ERROR.db_id,
                "state": "error",
            }
            error = UploadError(
                upload_id=upload_id,
                error_code=result["error"]["code"],
                error_params=result["error"]["params"],
            )
            all_errors.append(error)

        update["id_"] = upload_id
        order_number = merge_result.session_mapping.get(upload_id)
        update["order_number"] = order_number
        all_upload_updates.append(update)

    db_session.bulk_update_mappings(Upload, all_upload_updates)
    db_session.bulk_save_objects(all_errors)

    if all_totals:
        # the `UploadLevelTotals` have a unique constraint for the `upload`,
        # so we have to use a manual `insert` statement:
        stmt = (
            insert(UploadLevelTotals.__table__)
            .values(all_totals)
            .on_conflict_do_nothing()
        )
        db_session.execute(stmt)

    db_session.flush()


# TODO(swatinem): we should eventually remove `UploadLevelTotals` completely
def make_upload_totals(
    precision: int, rounding: str, upload_id: int, totals: ReportTotals
) -> dict:
    if totals.coverage is not None:
        coverage = precise_round(Decimal(totals.coverage), precision, rounding)
    else:
        coverage = Decimal(0)

    return dict(
        upload_id=upload_id,
        branches=totals.branches,
        coverage=coverage,
        hits=totals.hits,
        lines=totals.lines,
        methods=totals.methods,
        misses=totals.misses,
        partials=totals.partials,
        files=totals.files,
    )


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
