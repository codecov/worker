import logging

from shared.labelanalysis import LabelAnalysisRequestState

from app import celery_app
from database.models.labelanalysis import LabelAnalysisRequest
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class LabelAnalysisRequestProcessingTask(BaseCodecovTask):
    # TODO: Move name to shared
    name = "app.tasks.label_analysis"

    async def run_async(self, db_session, request_id, *args, **kwargs):
        label_analysis_request = (
            db_session.query(LabelAnalysisRequest)
            .filter(LabelAnalysisRequest.id_ == request_id)
            .first()
        )
        log.info("Starting label analysis request", extra=dict(request_id=request_id))
        result = self.calculate_result(label_analysis_request)
        label_analysis_request.result = result
        label_analysis_request.state_id = LabelAnalysisRequestState.finished.value
        return {
            "success": True,
        }

    def calculate_result(self, label_analysis_request: LabelAnalysisRequest):
        return {"not": "ready"}


RegisteredLabelAnalysisRequestProcessingTask = celery_app.register_task(
    LabelAnalysisRequestProcessingTask()
)
label_analysis_task = celery_app.tasks[
    RegisteredLabelAnalysisRequestProcessingTask.name
]
