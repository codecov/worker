# -*- coding: utf-8 -*-

import itertools
import logging
import random
import typing
from dataclasses import dataclass

import sentry_sdk
from shared.reports.resources import Report
from shared.utils.sessions import Session, SessionType

from database.models.reports import Upload
from helpers.exceptions import ReportEmptyError, ReportExpiredException
from helpers.labels import get_all_report_labels, get_labels_per_session
from rollouts import USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID
from services.path_fixer import PathFixer
from services.report.parser.types import ParsedRawReport
from services.report.report_builder import ReportBuilder, SpecialLabelsEnum
from services.report.report_processor import process_report
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)

DEFAULT_LABEL_INDEX = {
    SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label
}


@dataclass
class SessionAdjustmentResult:
    fully_deleted_sessions: list[int]
    partially_deleted_sessions: list[int]


@dataclass
class UploadProcessingResult:
    report: Report  # NOTE: this is just returning the input argument, and primarily used in tests
    session_adjustment: SessionAdjustmentResult  # NOTE: this is only ever used in tests


@sentry_sdk.trace
def process_raw_upload(
    commit_yaml,
    report: Report,
    raw_reports: ParsedRawReport,
    flags,
    session: Session,
    upload: Upload | None = None,
) -> UploadProcessingResult:
    toc, env = None, None

    # ----------------------
    # Extract `git ls-files`
    # ----------------------
    if raw_reports.has_toc():
        toc = raw_reports.get_toc()
    if raw_reports.has_env():
        env = raw_reports.get_env()

    path_fixer = PathFixer.init_from_user_yaml(
        commit_yaml=commit_yaml, toc=toc, flags=flags
    )

    # ------------------
    # Extract bash fixes
    # ------------------
    if raw_reports.has_report_fixes():
        ignored_file_lines = raw_reports.get_report_fixes(path_fixer)
    else:
        ignored_file_lines = None

    if env:
        session.env = dict([e.split("=", 1) for e in env.split("\n") if "=" in e])

    if flags:
        session.flags = flags

    skip_files = set()
    # [javascript] check for both coverage.json and coverage/coverage.lcov
    for report_file in raw_reports.get_uploaded_files():
        if report_file.filename == "coverage/coverage.json":
            skip_files.add("coverage/coverage.lcov")

    temporary_report = Report()

    should_use_encoded_labels = (
        upload
        and USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID.check_value(
            identifier=upload.report.commit.repository.repoid, default=False
        )
    )
    if should_use_encoded_labels:
        # We initialize the labels_index (which defaults to {}) to force the special label
        # to always be index 0
        temporary_report.labels_index = dict(DEFAULT_LABEL_INDEX)

    joined = True
    for flag in flags or []:
        if read_yaml_field(commit_yaml, ("flags", flag, "joined")) is False:
            log.info(
                "Customer is using joined=False feature", extra=dict(flag_used=flag)
            )
            joined = False  # TODO: ensure this works for parallel

    # ---------------
    # Process reports
    # ---------------
    ignored_lines = ignored_file_lines or {}
    for report_file in raw_reports.get_uploaded_files():
        current_filename = report_file.filename
        if report_file.contents:
            if current_filename in skip_files:
                log.info("Skipping file %s", current_filename)
                continue
            path_fixer_to_use = path_fixer.get_relative_path_aware_pathfixer(
                current_filename
            )

            report_builder_to_use = ReportBuilder(
                commit_yaml,
                session.id,
                ignored_lines,
                path_fixer_to_use,
                should_use_encoded_labels,
            )
            try:
                report_from_file = process_report(
                    report=report_file, report_builder=report_builder_to_use
                )
            except ReportExpiredException as r:
                r.filename = current_filename
                # FIXME: this will raise/abort processing *all* the files within an upload,
                # even though maybe just one of those files is expired.
                raise

            if report_from_file:
                if should_use_encoded_labels:
                    # Copies the labels from report into temporary_report
                    # If needed
                    make_sure_label_indexes_match(temporary_report, report_from_file)
                temporary_report.merge(report_from_file, joined=True)
            path_fixer_to_use.log_abnormalities()

    _possibly_log_pathfixer_unusual_results(path_fixer, session.id)

    if not temporary_report:
        raise ReportEmptyError("No files found in report.")

    if (
        should_use_encoded_labels
        and temporary_report.labels_index == DEFAULT_LABEL_INDEX
    ):
        # This means that, even though this report _could_ use encoded labels,
        # none of the reports processed contributed any new labels to it.
        # So we assume there are no labels and just reset the _labels_index of temporary_report
        temporary_report.labels_index = None

    # Now we actually add the session to the original_report
    # Because we know that the processing was successful
    _sessionid, session = report.add_session(session, use_id_from_session=True)
    # Adjust sessions removed carryforward sessions that are being replaced
    session_adjustment = _adjust_sessions(
        report,
        temporary_report,
        to_merge_session=session,
        current_yaml=commit_yaml,
        upload=upload,
    )

    report.merge(temporary_report, joined=joined)
    session.totals = temporary_report.totals
    return UploadProcessingResult(report=report, session_adjustment=session_adjustment)


@sentry_sdk.trace
def make_sure_orginal_report_is_using_label_ids(original_report: Report):
    """Makes sure that the original_report (that was pulled from DB)
    has CoverageDatapoints that encode label_ids and not actual labels.
    """
    # Always point the special label to index 0
    reverse_index_cache = {
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index
    }
    if original_report.labels_index is None:
        original_report.labels_index = {}
    labels_index = original_report.labels_index

    if (
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index
        not in labels_index
    ):
        labels_index[
            SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index
        ] = SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label

    def possibly_translate_label(label_or_id: typing.Union[str, int]) -> int:
        if isinstance(label_or_id, int):
            return label_or_id
        if label_or_id in reverse_index_cache:
            return reverse_index_cache[label_or_id]
        # Search for label in the report index
        for idx, label in labels_index.items():
            if label == label_or_id:
                reverse_index_cache[label] = idx
                return idx
        # Label is not present. Add to index.
        # Notice that this never picks index 0, that is reserved for the special label
        new_index = max(labels_index.keys()) + 1
        reverse_index_cache[label_or_id] = new_index
        # It's OK to update this here because it's inside the
        # UploadProcessing lock, so it's exclusive access
        labels_index[new_index] = label_or_id
        return new_index

    for report_file in original_report:
        for _, report_line in report_file.lines:
            if report_line.datapoints:
                for datapoint in report_line.datapoints:
                    datapoint.label_ids = [
                        possibly_translate_label(label_or_id)
                        for label_or_id in datapoint.label_ids
                    ]
                report_line.datapoints.sort(key=lambda x: x.key_sorting_tuple())


@sentry_sdk.trace
def make_sure_label_indexes_match(
    original_report: Report, to_merge_report: Report
) -> None:
    """Makes sure that the indexes of both reports point to the same labels.
    Uses the original_report as reference, and fixes the to_merge_report as needed
    it also extendes the original_report.labels_index with new labels as needed.
    """
    if to_merge_report.labels_index is None or original_report.labels_index is None:
        # The new report doesn't have labels to fix
        return

    # Map label --> index_in_original_report
    reverse_index: typing.Dict[str, int] = {
        t[1]: t[0] for t in original_report.labels_index.items()
    }
    # Map index_in_to_merge_report --> index_in_original_report
    indexes_to_fix: typing.Dict[int, int] = {}
    next_idx = max(original_report.labels_index.keys()) + 1
    for idx, label in to_merge_report.labels_index.items():
        # Special case for the special label, which is SpecialLabelsEnum in to_merge_report
        # But in the original_report it points to a string
        if label == SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER:
            if (
                idx
                != SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index
            ):
                indexes_to_fix[idx] = (
                    SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index
                )
        if label not in reverse_index:
            # It's a new label that doesn't exist in the original_report
            original_report.labels_index[next_idx] = label
            indexes_to_fix[idx] = next_idx
            next_idx += 1
        elif reverse_index[label] == idx:
            # This label matches the index on the original report
            continue
        else:
            # Here the label doesn't match the index in the original report
            indexes_to_fix[idx] = reverse_index[label]

    # Fix indexes in to_merge_report.
    for report_file in to_merge_report:
        for _, report_line in report_file.lines:
            if report_line.datapoints:
                for datapoint in report_line.datapoints:
                    datapoint.label_ids = [
                        indexes_to_fix.get(label_id, label_id)
                        for label_id in datapoint.label_ids
                    ]


@sentry_sdk.trace
def _adjust_sessions(
    original_report: Report,
    to_merge_report: Report,
    to_merge_session,
    current_yaml,
    upload: Upload | None = None,
):
    session_ids_to_fully_delete = []
    session_ids_to_partially_delete = []
    to_merge_flags = to_merge_session.flags or []
    flags_under_carryforward_rules = [
        f for f in to_merge_flags if current_yaml.flag_has_carryfoward(f)
    ]
    to_partially_overwrite_flags = [
        f
        for f in flags_under_carryforward_rules
        if current_yaml.get_flag_configuration(f).get("carryforward_mode") == "labels"
    ]
    to_fully_overwrite_flags = [
        f
        for f in flags_under_carryforward_rules
        if f not in to_partially_overwrite_flags
    ]
    if upload is not None:
        commit_id = upload.report.commit_id
    if upload is None and to_partially_overwrite_flags:
        log.warning("Upload is None, but there are partial_overwrite_flags present")

    if (
        upload
        and USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID.check_value(
            identifier=upload.report.commit.repository.repoid, default=False
        )
        and to_partially_overwrite_flags
    ):
        # Make sure that the labels in the reports are in a good state to merge them
        make_sure_orginal_report_is_using_label_ids(original_report)
        make_sure_label_indexes_match(original_report, to_merge_report)

    if to_fully_overwrite_flags or to_partially_overwrite_flags:
        for sess_id, curr_sess in original_report.sessions.items():
            if curr_sess.session_type == SessionType.carriedforward:
                if curr_sess.flags:
                    if any(f in to_fully_overwrite_flags for f in curr_sess.flags):
                        session_ids_to_fully_delete.append(sess_id)
                    if any(f in to_partially_overwrite_flags for f in curr_sess.flags):
                        session_ids_to_partially_delete.append(sess_id)

    actually_fully_deleted_sessions = set()
    if session_ids_to_fully_delete:
        extra = dict(
            deleted_sessions=session_ids_to_fully_delete,
        )
        if upload is not None:
            extra["commit_id"] = commit_id
        log.info(
            "Deleted multiple sessions due to carriedforward overwrite",
            extra=extra,
        )
        original_report.delete_multiple_sessions(session_ids_to_fully_delete)
        actually_fully_deleted_sessions.update(session_ids_to_fully_delete)

    if session_ids_to_partially_delete:
        extra = dict(
            deleted_sessions=session_ids_to_partially_delete,
        )
        if upload is not None:
            extra["commit_id"] = commit_id
        log.info(
            "Partially deleting sessions due to label carryforward overwrite",
            extra=extra,
        )
        all_labels = get_all_report_labels(to_merge_report)
        original_report.delete_labels(session_ids_to_partially_delete, all_labels)
        for s in session_ids_to_partially_delete:
            labels_now = get_labels_per_session(original_report, s)
            if not labels_now:
                log.info(
                    "Session has now no new labels, deleting whole session",
                    extra=dict(commit_id=commit_id) if upload is not None else dict(),
                )
                actually_fully_deleted_sessions.add(s)
                original_report.delete_session(s)

    return SessionAdjustmentResult(
        sorted(actually_fully_deleted_sessions),
        sorted(set(session_ids_to_partially_delete) - actually_fully_deleted_sessions),
    )


def _possibly_log_pathfixer_unusual_results(path_fixer: PathFixer, sessionid: int):
    actual_path_fixes = {
        after: before
        for (after, before) in path_fixer.calculated_paths.items()
        if after is not None
    }
    if len(actual_path_fixes) > 0:
        log.info(
            "Example path fixes for this raw upload",
            extra={
                "fixes": list(itertools.islice(actual_path_fixes.items(), 10)),
                "disable_default_pathfixes": path_fixer.should_disable_default_pathfixes,
            },
        )

    if path_fixer.calculated_paths.get(None):
        ignored_files = sorted(path_fixer.calculated_paths.pop(None))
        log.info(
            "Some files were ignored",
            extra=dict(
                number=len(ignored_files),
                paths=random.sample(ignored_files, min(100, len(ignored_files))),
                session=sessionid,
            ),
        )
    path_with_same_results = [
        (key, len(value), list(value)[:10])
        for key, value in path_fixer.calculated_paths.items()
        if len(value) >= 2
    ]
    if path_with_same_results:
        log.info(
            "Two different files went to the same result",
            extra=dict(
                number_of_paths=len(path_with_same_results),
                paths=path_with_same_results[:50],
                session=sessionid,
            ),
        )
