import logging
from typing import Dict, List, NamedTuple, Optional, Set, Tuple, TypedDict, Union

import sentry_sdk
from asgiref.sync import async_to_sync
from shared.celery_config import label_analysis_task_name
from shared.labelanalysis import LabelAnalysisRequestState
from sqlalchemy.orm import Session

from app import celery_app
from database.models.labelanalysis import (
    LabelAnalysisProcessingError,
    LabelAnalysisProcessingErrorCode,
    LabelAnalysisRequest,
)
from database.models.staticanalysis import StaticAnalysisSuite
from helpers.labels import get_all_report_labels, get_labels_per_session
from helpers.metrics import metrics
from helpers.telemetry import log_simple_metric
from services.report import Report, ReportService
from services.report.report_builder import SpecialLabelsEnum
from services.repository import get_repo_provider_service
from services.static_analysis import StaticAnalysisComparisonService
from services.static_analysis.git_diff_parser import DiffChange, parse_git_diff_json
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


GLOBAL_LEVEL_LABEL = (
    SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label
)

GLOBAL_LEVEL_LABEL_IDX = (
    SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index
)


class LinesRelevantToChangeInFile(TypedDict):
    all: bool
    lines: Set[int]


class LinesRelevantToChange(TypedDict):
    all: bool
    files: Dict[str, Optional[LinesRelevantToChangeInFile]]


class ExistingLabelSetsEncoded(NamedTuple):
    all_report_labels: Set[int]
    executable_lines_labels: Set[int]
    global_level_labels: Set[int]
    are_labels_encoded: bool = True


class ExistingLabelSetsNotEncoded(NamedTuple):
    all_report_labels: Set[str]
    executable_lines_labels: Set[str]
    global_level_labels: Set[str]
    are_labels_encoded: bool = False


ExistingLabelSets = Union[ExistingLabelSetsEncoded, ExistingLabelSetsNotEncoded]
PossiblyEncodedLabelSet = Union[Set[str], Set[int]]


class LabelAnalysisRequestProcessingTask(
    BaseCodecovTask, name=label_analysis_task_name
):
    errors: List[LabelAnalysisProcessingError] = None
    dbsession: Session = None

    def reset_task_context(self):
        """Resets the task's attributes to None to avoid spilling information
        between task calls in the same process.
        https://docs.celeryq.dev/en/latest/userguide/tasks.html#instantiation
        """
        self.errors = None
        self.dbsession = None

    def run_impl(self, db_session, request_id, *args, **kwargs):
        self.errors = []
        self.dbsession = db_session
        label_analysis_request = (
            db_session.query(LabelAnalysisRequest)
            .filter(LabelAnalysisRequest.id_ == request_id)
            .first()
        )
        if label_analysis_request is None:
            metrics.incr("label_analysis_task.failed_to_calculate.larq_not_found")
            log.error(
                "LabelAnalysisRequest not found", extra=dict(request_id=request_id)
            )
            self.add_processing_error(
                larq_id=request_id,
                error_code=LabelAnalysisProcessingErrorCode.NOT_FOUND,
                error_msg="LabelAnalysisRequest not found",
                error_extra=dict(),
            )
            response = {
                "success": False,
                "present_report_labels": [],
                "present_diff_labels": [],
                "absent_labels": [],
                "global_level_labels": [],
                "errors": self.errors,
            }
            self.reset_task_context()
            return response
        log.info(
            "Starting label analysis request",
            extra=dict(
                request_id=request_id,
                external_id=label_analysis_request.external_id,
                commit=label_analysis_request.head_commit.commitid,
            ),
        )

        if label_analysis_request.state_id == LabelAnalysisRequestState.FINISHED.db_id:
            # Indicates that this request has been calculated already
            # We might need to update the requested labels
            response = self._handle_larq_already_calculated(label_analysis_request)
            self.reset_task_context()
            return response

        try:
            lines_relevant_to_diff: Optional[LinesRelevantToChange] = (
                self._get_lines_relevant_to_diff(label_analysis_request)
            )
            base_report = self._get_base_report(label_analysis_request)

            if lines_relevant_to_diff and base_report:
                existing_labels: ExistingLabelSets = self._get_existing_labels(
                    base_report, lines_relevant_to_diff
                )
                if existing_labels.are_labels_encoded:
                    # Translate label_ids
                    def partial_fn_to_apply(label_id_set):
                        return self._lookup_label_ids(
                            report=base_report, label_ids=label_id_set
                        )

                    existing_labels = ExistingLabelSetsNotEncoded(
                        all_report_labels=partial_fn_to_apply(
                            existing_labels.all_report_labels
                        ),
                        executable_lines_labels=partial_fn_to_apply(
                            existing_labels.executable_lines_labels
                        ),
                        global_level_labels=partial_fn_to_apply(
                            existing_labels.global_level_labels
                        ),
                        are_labels_encoded=False,
                    )

                requested_labels = self._get_requested_labels(label_analysis_request)
                result = self.calculate_final_result(
                    requested_labels=requested_labels,
                    existing_labels=existing_labels,
                    commit_sha=label_analysis_request.head_commit.commitid,
                )
                label_analysis_request.result = result
                label_analysis_request.state_id = (
                    LabelAnalysisRequestState.FINISHED.db_id
                )
                metrics.incr("label_analysis_task.success")
                response = {
                    "success": True,
                    "present_report_labels": result["present_report_labels"],
                    "present_diff_labels": result["present_diff_labels"],
                    "absent_labels": result["absent_labels"],
                    "global_level_labels": result["global_level_labels"],
                    "errors": self.errors,
                }
                self.reset_task_context()
                return response
        except Exception:
            # temporary general catch while we find possible problems on this
            metrics.incr("label_analysis_task.failed_to_calculate.exception")
            log.exception(
                "Label analysis failed to calculate",
                extra=dict(
                    request_id=request_id,
                    commit=label_analysis_request.head_commit.commitid,
                    external_id=label_analysis_request.external_id,
                ),
            )
            label_analysis_request.result = None
            label_analysis_request.state_id = LabelAnalysisRequestState.ERROR.db_id
            self.add_processing_error(
                larq_id=request_id,
                error_code=LabelAnalysisProcessingErrorCode.FAILED,
                error_msg="Failed to calculate",
                error_extra=dict(),
            )
            response = {
                "success": False,
                "present_report_labels": [],
                "present_diff_labels": [],
                "absent_labels": [],
                "global_level_labels": [],
                "errors": self.errors,
            }
            self.reset_task_context()
            return response
        metrics.incr("label_analysis_task.failed_to_calculate.missing_info")
        log.warning(
            "We failed to get some information that was important to label analysis",
            extra=dict(
                has_relevant_lines=(lines_relevant_to_diff is not None),
                has_base_report=(base_report is not None),
                commit=label_analysis_request.head_commit.commitid,
                external_id=label_analysis_request.external_id,
                request_id=request_id,
            ),
        )
        label_analysis_request.state_id = LabelAnalysisRequestState.FINISHED.db_id
        result_to_save = {
            "success": True,
            "present_report_labels": [],
            "present_diff_labels": [],
            "absent_labels": label_analysis_request.requested_labels,
            "global_level_labels": [],
        }
        label_analysis_request.result = result_to_save
        result_to_return = {**result_to_save, "errors": self.errors}
        self.reset_task_context()
        return result_to_return

    def add_processing_error(
        self,
        larq_id: int,
        error_code: LabelAnalysisProcessingErrorCode,
        error_msg: str,
        error_extra: dict,
    ):
        error = LabelAnalysisProcessingError(
            label_analysis_request_id=larq_id,
            error_code=error_code.value,
            error_params=dict(message=error_msg, extra=error_extra),
        )
        self.errors.append(error.to_representation())
        self.dbsession.add(error)

    def _handle_larq_already_calculated(self, larq: LabelAnalysisRequest):
        # This means we already calculated everything
        # Except possibly the absent labels
        log.info(
            "Label analysis request was already calculated",
            extra=dict(
                request_id=larq.id,
                external_id=larq.external_id,
                commit=larq.head_commit.commitid,
            ),
        )
        if larq.requested_labels:
            saved_result = larq.result
            all_saved_labels = set(
                saved_result.get("present_report_labels", [])
                + saved_result.get("present_diff_labels", [])
                + saved_result.get("global_level_labels", [])
            )
            executable_lines_saved_labels = set(
                saved_result.get("present_diff_labels", [])
            )
            global_saved_labels = set(saved_result.get("global_level_labels", []))
            result = self.calculate_final_result(
                requested_labels=larq.requested_labels,
                existing_labels=ExistingLabelSetsNotEncoded(
                    all_saved_labels, executable_lines_saved_labels, global_saved_labels
                ),
                commit_sha=larq.head_commit.commitid,
            )
            larq.result = result  # Save the new result
            metrics.incr("label_analysis_task.already_calculated.new_result")
            return {**result, "success": True, "errors": []}
        # No requested labels mean we don't have any new information
        # So we don't need to calculate again
        # This shouldn't actually happen
        metrics.incr("label_analysis_task.already_calculated.same_result")
        return {**larq.result, "success": True, "errors": []}

    def _lookup_label_ids(self, report: Report, label_ids: Set[int]) -> Set[str]:
        labels: Set[str] = set()
        for label_id in label_ids:
            # This can raise shared.reports.exceptions.LabelNotFoundError
            # But (1) we shouldn't let that happen and (2) there's no recovering from it
            # So we should let that happen to surface bugs to us
            labels.add(report.lookup_label_by_id(label_id))
        return labels

    def _get_requested_labels(self, label_analysis_request: LabelAnalysisRequest):
        if label_analysis_request.requested_labels:
            return label_analysis_request.requested_labels
        # This is the case where the CLI PATCH the requested labels after collecting them
        self.dbsession.refresh(label_analysis_request, ["requested_labels"])
        return label_analysis_request.requested_labels

    @sentry_sdk.trace
    def _get_existing_labels(
        self, report: Report, lines_relevant_to_diff: LinesRelevantToChange
    ) -> ExistingLabelSets:
        all_report_labels = self.get_all_report_labels(report)
        (
            executable_lines_labels,
            global_level_labels,
        ) = self.get_executable_lines_labels(report, lines_relevant_to_diff)

        if len(all_report_labels) > 0:
            # Check if report labels are encoded or not
            test_label = all_report_labels.pop()
            are_labels_encoded = isinstance(test_label, int)
            all_report_labels.add(test_label)
        else:
            # There are no labels in the report
            are_labels_encoded = False

        class_to_use = (
            ExistingLabelSetsEncoded
            if are_labels_encoded
            else ExistingLabelSetsNotEncoded
        )

        return class_to_use(
            all_report_labels=all_report_labels,
            executable_lines_labels=executable_lines_labels,
            global_level_labels=global_level_labels,
        )

    @sentry_sdk.trace
    def _get_lines_relevant_to_diff(self, label_analysis_request: LabelAnalysisRequest):
        parsed_git_diff = self._get_parsed_git_diff(label_analysis_request)
        if parsed_git_diff:
            executable_lines_relevant_to_diff = self.get_relevant_executable_lines(
                label_analysis_request, parsed_git_diff
            )
            # This line will be useful for debugging
            # And to tweak the heuristics
            log.info(
                "Lines relevant to diff",
                extra=dict(
                    lines_relevant_to_diff=executable_lines_relevant_to_diff,
                    commit=label_analysis_request.head_commit.commitid,
                    external_id=label_analysis_request.external_id,
                    request_id=label_analysis_request.id_,
                ),
            )
            return executable_lines_relevant_to_diff
        return None

    @sentry_sdk.trace
    def _get_parsed_git_diff(
        self, label_analysis_request: LabelAnalysisRequest
    ) -> Optional[List[DiffChange]]:
        try:
            repo_service = get_repo_provider_service(
                label_analysis_request.head_commit.repository
            )
            git_diff = async_to_sync(repo_service.get_compare)(
                label_analysis_request.base_commit.commitid,
                label_analysis_request.head_commit.commitid,
            )
            try:
                git_pr = async_to_sync(repo_service.find_pull_request)(
                    label_analysis_request.head_commit.commitid,
                )
                pr_files = async_to_sync(repo_service.get_pull_request_files)(
                    git_pr["id"]
                )
            except Exception:
                pr_files = []
            return list(parse_git_diff_json(git_diff, pr_files))
        except Exception:
            # temporary general catch while we find possible problems on this
            log.exception(
                "Label analysis failed to parse git diff",
                extra=dict(
                    request_id=label_analysis_request.id,
                    external_id=label_analysis_request.external_id,
                    commit=label_analysis_request.head_commit.commitid,
                ),
            )
            self.add_processing_error(
                larq_id=label_analysis_request.id,
                error_code=LabelAnalysisProcessingErrorCode.FAILED,
                error_msg="Failed to parse git diff",
                error_extra=dict(
                    head_commit=label_analysis_request.head_commit.commitid,
                    base_commit=label_analysis_request.base_commit.commitid,
                ),
            )
            return None

    @sentry_sdk.trace
    def _get_base_report(
        self, label_analysis_request: LabelAnalysisRequest
    ) -> Optional[Report]:
        base_commit = label_analysis_request.base_commit
        current_yaml = get_repo_yaml(base_commit.repository)
        report_service = ReportService(current_yaml)
        report: Report = report_service.get_existing_report_for_commit(base_commit)
        if report is None:
            log.warning(
                "No report found for label analysis",
                extra=dict(
                    request_id=label_analysis_request.id,
                    commit=label_analysis_request.head_commit.commitid,
                ),
            )
            self.add_processing_error(
                larq_id=label_analysis_request.id,
                error_code=LabelAnalysisProcessingErrorCode.MISSING_DATA,
                error_msg="Missing base report",
                error_extra=dict(
                    head_commit=label_analysis_request.head_commit.commitid,
                    base_commit=label_analysis_request.base_commit.commitid,
                ),
            )
        return report

    @sentry_sdk.trace
    def calculate_final_result(
        self,
        *,
        requested_labels: Optional[List[str]],
        existing_labels: ExistingLabelSetsNotEncoded,
        commit_sha: str,
    ):
        all_report_labels = existing_labels.all_report_labels
        executable_lines_labels = existing_labels.executable_lines_labels
        global_level_labels = existing_labels.global_level_labels
        log.info(
            "Final info",
            extra=dict(
                executable_lines_labels=sorted(executable_lines_labels),
                all_report_labels=all_report_labels,
                requested_labels=requested_labels,
                global_level_labels=sorted(global_level_labels),
                commit=commit_sha,
            ),
        )
        log_simple_metric("label_analysis.tests_saved_count", len(all_report_labels))
        log_simple_metric(
            "label_analysis.requests_with_requested_labels",
            float(requested_labels is not None),
        )
        if requested_labels is not None:
            requested_labels = set(requested_labels)
            ans = {
                "present_report_labels": sorted(all_report_labels & requested_labels),
                "present_diff_labels": sorted(
                    executable_lines_labels & requested_labels
                ),
                "absent_labels": sorted(requested_labels - all_report_labels),
                "global_level_labels": sorted(global_level_labels & requested_labels),
            }
            log_simple_metric(
                "label_analysis.requested_labels_count", len(requested_labels)
            )
            log_simple_metric(
                "label_analysis.tests_to_run_count",
                len(
                    ans["present_diff_labels"]
                    + ans["global_level_labels"]
                    + ans["absent_labels"]
                ),
            )
            return ans
        log_simple_metric(
            "label_analysis.tests_to_run_count",
            len(executable_lines_labels | global_level_labels),
        )
        return {
            "present_report_labels": sorted(all_report_labels),
            "present_diff_labels": sorted(executable_lines_labels),
            "absent_labels": [],
            "global_level_labels": sorted(global_level_labels),
        }

    @sentry_sdk.trace
    def get_relevant_executable_lines(
        self, label_analysis_request: LabelAnalysisRequest, parsed_git_diff
    ):
        db_session = label_analysis_request.get_db_session()
        base_static_analysis: StaticAnalysisSuite = (
            db_session.query(StaticAnalysisSuite)
            .filter(
                StaticAnalysisSuite.commit_id == label_analysis_request.base_commit_id,
            )
            .first()
        )
        head_static_analysis: StaticAnalysisSuite = (
            db_session.query(StaticAnalysisSuite)
            .filter(
                StaticAnalysisSuite.commit_id == label_analysis_request.head_commit_id,
            )
            .first()
        )
        if not base_static_analysis or not head_static_analysis:
            # TODO : Proper handling of this case
            log.info(
                "Trying to make prediction where there are no static analyses",
                extra=dict(
                    base_static_analysis=base_static_analysis.id_
                    if base_static_analysis is not None
                    else None,
                    head_static_analysis=head_static_analysis.id_
                    if head_static_analysis is not None
                    else None,
                    commit=label_analysis_request.head_commit.commitid,
                ),
            )
            self.add_processing_error(
                larq_id=label_analysis_request.id,
                error_code=LabelAnalysisProcessingErrorCode.MISSING_DATA,
                error_msg="Missing static analysis info",
                error_extra=dict(
                    head_commit=label_analysis_request.head_commit.commitid,
                    base_commit=label_analysis_request.base_commit.commitid,
                    has_base_static_analysis=(base_static_analysis is not None),
                    has_head_static_analysis=(head_static_analysis is not None),
                ),
            )
            return None
        static_analysis_comparison_service = StaticAnalysisComparisonService(
            base_static_analysis,
            head_static_analysis,
            parsed_git_diff,
        )
        return static_analysis_comparison_service.get_base_lines_relevant_to_change()

    @sentry_sdk.trace
    def get_executable_lines_labels(
        self, report: Report, executable_lines: LinesRelevantToChange
    ) -> Tuple[PossiblyEncodedLabelSet, PossiblyEncodedLabelSet]:
        if executable_lines["all"]:
            return (self.get_all_report_labels(report), set())
        full_sessions = set()
        labels: PossiblyEncodedLabelSet = set()
        global_level_labels = set()
        # Prime piece of code to be rust-ifyied
        for name, file_executable_lines in executable_lines["files"].items():
            rf = report.get(name)
            if rf and file_executable_lines:
                if file_executable_lines["all"]:
                    for line_number, line in rf.lines:
                        if line and line.datapoints:
                            for datapoint in line.datapoints:
                                dp_labels = datapoint.label_ids or []
                                labels.update(dp_labels)
                                if (
                                    # If labels are encoded
                                    GLOBAL_LEVEL_LABEL_IDX in dp_labels
                                    # If labels are NOT encoded
                                    or GLOBAL_LEVEL_LABEL in dp_labels
                                ):
                                    full_sessions.add(datapoint.sessionid)
                else:
                    for line_number in file_executable_lines["lines"]:
                        line = rf.get(line_number)
                        if line and line.datapoints:
                            for datapoint in line.datapoints:
                                dp_labels = datapoint.label_ids or []
                                labels.update(dp_labels)
                                if (
                                    # If labels are encoded
                                    GLOBAL_LEVEL_LABEL_IDX in dp_labels
                                    # If labels are NOT encoded
                                    or GLOBAL_LEVEL_LABEL in dp_labels
                                ):
                                    full_sessions.add(datapoint.sessionid)
        for sess_id in full_sessions:
            global_level_labels.update(self.get_labels_per_session(report, sess_id))
        return (
            labels - set([GLOBAL_LEVEL_LABEL_IDX, GLOBAL_LEVEL_LABEL]),
            global_level_labels,
        )

    def get_labels_per_session(self, report: Report, sess_id: int):
        return get_labels_per_session(report, sess_id)

    def get_all_report_labels(self, report: Report) -> set:
        return get_all_report_labels(report)


RegisteredLabelAnalysisRequestProcessingTask = celery_app.register_task(
    LabelAnalysisRequestProcessingTask()
)
label_analysis_task = celery_app.tasks[
    RegisteredLabelAnalysisRequestProcessingTask.name
]
