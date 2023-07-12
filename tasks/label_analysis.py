import logging
from typing import List, Optional, Set, Tuple

import sentry_sdk
from shared import torngit
from shared.celery_config import label_analysis_task_name
from shared.labelanalysis import LabelAnalysisRequestState

from app import celery_app
from database.models.core import Commit
from database.models.labelanalysis import LabelAnalysisRequest
from database.models.staticanalysis import StaticAnalysisSuite
from helpers.labels import get_all_report_labels, get_labels_per_session
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


class LabelAnalysisRequestProcessingTask(BaseCodecovTask):
    name = label_analysis_task_name

    async def run_async(self, db_session, request_id, *args, **kwargs):
        label_analysis_request = (
            db_session.query(LabelAnalysisRequest)
            .filter(LabelAnalysisRequest.id_ == request_id)
            .first()
        )
        if label_analysis_request is None:
            log.error(
                "LabelAnalysisRequest not found", extra=dict(request_id=request_id)
            )
            return {
                "success": False,
                "present_report_labels": None,
                "present_diff_labels": None,
                "absent_labels": None,
                "global_level_labels": None,
            }
        log.info(
            "Starting label analysis request",
            extra=dict(
                request_id=request_id,
                commit=label_analysis_request.head_commit.commitid,
            ),
        )
        try:
            lines_relevant_to_diff = await self._get_lines_relevant_to_diff(
                label_analysis_request
            )
            base_report = self._get_base_report(label_analysis_request)

            if lines_relevant_to_diff and base_report:
                exisisting_labels = self._get_existing_labels(
                    base_report, lines_relevant_to_diff
                )
                requested_labels = self._get_requested_labels(
                    label_analysis_request, db_session
                )
                result = self.calculate_final_result(
                    requested_labels=requested_labels,
                    existing_labels=exisisting_labels,
                    commit_sha=label_analysis_request.head_commit.commitid,
                )
                label_analysis_request.result = result
                label_analysis_request.state_id = (
                    LabelAnalysisRequestState.FINISHED.db_id
                )
                return {
                    "success": True,
                    "present_report_labels": result["present_report_labels"],
                    "present_diff_labels": result["present_diff_labels"],
                    "absent_labels": result["absent_labels"],
                    "global_level_labels": result["global_level_labels"],
                }
        except Exception:
            # temporary general catch while we find possible problems on this
            log.exception(
                "Label analysis failed to calculate",
                extra=dict(
                    request_id=request_id,
                    commit=label_analysis_request.head_commit.commitid,
                ),
            )
            label_analysis_request.result = None
            label_analysis_request.state_id = LabelAnalysisRequestState.ERROR.db_id
            return {
                "success": False,
                "present_report_labels": None,
                "present_diff_labels": None,
                "absent_labels": None,
                "global_level_labels": None,
            }
        log.warning(
            "We failed to get some information that was important to label analysis",
            extra=dict(
                has_relevant_lines=(lines_relevant_to_diff is not None),
                has_base_report=(base_report is not None),
                commit=label_analysis_request.head_commit.commitid,
            ),
        )
        label_analysis_request.state_id = LabelAnalysisRequestState.FINISHED.db_id
        result = {
            "success": True,
            "present_report_labels": None,
            "present_diff_labels": None,
            "absent_labels": label_analysis_request.requested_labels,
            "global_level_labels": None,
        }
        label_analysis_request.result = result
        return result

    def _get_requested_labels(
        self, label_analysis_request: LabelAnalysisRequest, dbsession
    ):
        if label_analysis_request.requested_labels:
            return label_analysis_request.requested_labels
        # This is the case where the CLI PATCH the requested labels after collecting them
        dbsession.refresh(label_analysis_request, ["requested_labels"])
        return label_analysis_request.requested_labels

    @sentry_sdk.trace
    def _get_existing_labels(
        self, report: Report, lines_relevant_to_diff
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        all_report_labels = self.get_all_report_labels(report)
        executable_lines_labels, global_level_labels = self.get_executable_lines_labels(
            report, lines_relevant_to_diff
        )
        return (all_report_labels, executable_lines_labels, global_level_labels)

    @sentry_sdk.trace
    async def _get_lines_relevant_to_diff(
        self, label_analysis_request: LabelAnalysisRequest
    ):
        parsed_git_diff = await self._get_parsed_git_diff(label_analysis_request)
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
                ),
            )
            return executable_lines_relevant_to_diff
        return None

    @sentry_sdk.trace
    async def _get_parsed_git_diff(
        self, label_analysis_request: LabelAnalysisRequest
    ) -> Optional[List[DiffChange]]:
        try:
            repo_service = get_repo_provider_service(
                label_analysis_request.head_commit.repository
            )
            git_diff = await repo_service.get_compare(
                label_analysis_request.base_commit.commitid,
                label_analysis_request.head_commit.commitid,
            )
            return list(parse_git_diff_json(git_diff))
        except Exception:
            # temporary general catch while we find possible problems on this
            log.exception(
                "Label analysis failed to parse git diff",
                extra=dict(
                    request_id=label_analysis_request.id,
                    commit=label_analysis_request.head_commit.commitid,
                ),
                exc_info=True,
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
        return report

    @sentry_sdk.trace
    def calculate_final_result(
        self,
        *,
        requested_labels: List[str],
        existing_labels: Tuple[Set[str], Set[str], Set[str]],
        commit_sha: str,
    ):
        (
            all_report_labels,
            executable_lines_labels,
            global_level_labels,
        ) = existing_labels
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
        if requested_labels is not None:
            requested_labels = set(requested_labels)
            all_report_labels = all_report_labels
            return {
                "present_report_labels": sorted(all_report_labels & requested_labels),
                "present_diff_labels": sorted(
                    executable_lines_labels & requested_labels
                ),
                "absent_labels": sorted(requested_labels - all_report_labels),
                "global_level_labels": sorted(global_level_labels & requested_labels),
            }
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
            return None
        static_analysis_comparison_service = StaticAnalysisComparisonService(
            base_static_analysis,
            head_static_analysis,
            parsed_git_diff,
        )
        return static_analysis_comparison_service.get_base_lines_relevant_to_change()

    @sentry_sdk.trace
    def get_executable_lines_labels(self, report: Report, executable_lines) -> set:
        if executable_lines["all"]:
            return (self.get_all_report_labels(report), set())
        full_sessions = set()
        labels = set()
        global_level_labels = set()
        # Prime piece of code to be rust-ifyied
        for name, file_executable_lines in executable_lines["files"].items():
            rf = report.get(name)
            if rf:
                if file_executable_lines["all"]:
                    for line_number, line in rf.lines:
                        if line and line.datapoints:
                            for datapoint in line.datapoints:
                                dp_labels = datapoint.labels or []
                                labels.update(dp_labels)
                                if GLOBAL_LEVEL_LABEL in dp_labels:
                                    full_sessions.add(datapoint.sessionid)
                else:
                    for line_number in file_executable_lines["lines"]:
                        line = rf.get(line_number)
                        if line and line.datapoints:
                            for datapoint in line.datapoints:
                                dp_labels = datapoint.labels or []
                                labels.update(dp_labels)
                                if GLOBAL_LEVEL_LABEL in dp_labels:
                                    full_sessions.add(datapoint.sessionid)
        for sess_id in full_sessions:
            global_level_labels.update(self.get_labels_per_session(report, sess_id))
        return (labels - set([GLOBAL_LEVEL_LABEL]), global_level_labels)

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
