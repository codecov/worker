import logging

from shared.labelanalysis import LabelAnalysisRequestState

from app import celery_app
from database.models.labelanalysis import LabelAnalysisRequest
from database.models.staticanalysis import StaticAnalysisSuite
from services.report import Report, ReportService
from services.repository import get_repo_provider_service
from services.static_analysis import StaticAnalysisComparisonService
from services.static_analysis.git_diff_parser import parse_git_diff_json
from services.yaml import get_repo_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class LabelAnalysisRequestProcessingTask(BaseCodecovTask):
    name = "app.tasks.label_analysis.process"

    async def run_async(self, db_session, request_id, *args, **kwargs):
        label_analysis_request = (
            db_session.query(LabelAnalysisRequest)
            .filter(LabelAnalysisRequest.id_ == request_id)
            .first()
        )
        log.info("Starting label analysis request", extra=dict(request_id=request_id))
        try:
            repo_service = get_repo_provider_service(
                label_analysis_request.head_commit.repository
            )
            git_diff = await repo_service.get_compare(
                label_analysis_request.base_commit.commitid,
                label_analysis_request.head_commit.commitid,
            )
            parsed_git_diff = list(parse_git_diff_json(git_diff))
            print(parsed_git_diff)
            result = self.calculate_result(label_analysis_request, parsed_git_diff)
        except Exception:
            # temporary general catch while we find possible problems on this
            log.exception(
                "Label analysis failed to calculate", extra=dict(request_id=request_id)
            )
            label_analysis_request.result = None
            label_analysis_request.state_id = LabelAnalysisRequestState.ERROR.db_id
            return {
                "success": False,
                "present_report_labels": None,
                "present_diff_labels": None,
                "absent_labels": None,
            }
        label_analysis_request.result = result
        label_analysis_request.state_id = LabelAnalysisRequestState.FINISHED.db_id
        return {
            "success": True,
            "present_report_labels": result["present_report_labels"],
            "present_diff_labels": result["present_diff_labels"],
            "absent_labels": result["absent_labels"],
        }

    def calculate_result(
        self, label_analysis_request: LabelAnalysisRequest, parsed_git_diff
    ):
        base_commit = label_analysis_request.base_commit
        current_yaml = get_repo_yaml(base_commit.repository)
        report_service = ReportService(current_yaml)
        report: Report = report_service.get_existing_report_for_commit(base_commit)
        all_report_labels = self.get_all_report_labels(report)
        executable_lines = self.get_relevant_executable_lines(
            label_analysis_request, parsed_git_diff
        )
        executable_lines_labels = self.get_executable_lines_labels(
            report, executable_lines
        )
        log.info(
            "Final info",
            extra=dict(
                executable_lines=executable_lines,
                executable_lines_labels=sorted(executable_lines_labels),
                all_report_labels=all_report_labels,
                requested_labels=label_analysis_request.requested_labels,
            ),
        )
        if label_analysis_request.requested_labels is not None:
            requested_labels = set(label_analysis_request.requested_labels)
            all_report_labels = all_report_labels
            return {
                "present_report_labels": sorted(all_report_labels & requested_labels),
                "present_diff_labels": sorted(
                    executable_lines_labels & requested_labels
                ),
                "absent_labels": sorted(requested_labels - all_report_labels),
            }
        return {
            "present_report_labels": sorted(all_report_labels),
            "present_diff_labels": sorted(executable_lines_labels),
            "absent_labels": [],
        }

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
            return None
        static_analysis_comparison_service = StaticAnalysisComparisonService(
            base_static_analysis,
            head_static_analysis,
            parsed_git_diff,
        )
        return static_analysis_comparison_service.get_base_lines_relevant_to_change()

    def get_executable_lines_labels(self, report: Report, executable_lines) -> set:
        if executable_lines["all"]:
            return self.get_all_report_labels(report)
        labels = set()
        for name, file_executable_lines in executable_lines["files"].items():
            rf = report.get(name)
            if rf:
                if file_executable_lines["all"]:
                    for line_number, line in rf.lines:
                        if line and line.datapoints:
                            for datapoint in line.datapoints:
                                labels.update(datapoint.labels or [])
                else:
                    for line_number in file_executable_lines["lines"]:
                        line = rf.get(line_number)
                        if line and line.datapoints:
                            for datapoint in line.datapoints:
                                labels.update(datapoint.labels or [])
        return labels

    def get_all_report_labels(self, report: Report) -> set:
        all_labels = set()
        for rf in report:
            for _, line in rf.lines:
                if line.datapoints:
                    for datapoint in line.datapoints:
                        all_labels.update(datapoint.labels or [])
        return all_labels


RegisteredLabelAnalysisRequestProcessingTask = celery_app.register_task(
    LabelAnalysisRequestProcessingTask()
)
label_analysis_task = celery_app.tasks[
    RegisteredLabelAnalysisRequestProcessingTask.name
]
