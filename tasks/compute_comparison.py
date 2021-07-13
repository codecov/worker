import logging

from app import celery_app
from tasks.base import BaseCodecovTask
from database.models import CompareCommit
from database.enums import CompareCommitState
from shared.celery_config import compute_comparison_task_name

log = logging.getLogger(__name__)


class ComputeComparisonTask(BaseCodecovTask):
    name = compute_comparison_task_name

    async def run_async(self, db_session, comparison_id, *args, **kwargs):
        log.info(f"Computing comparison", extra=dict(comparison_id=comparison_id))
        comparison = db_session.query(CompareCommit).get(comparison_id)
        comparison.state = CompareCommitState.processed
        return None


RegisteredComputeComparisonTask = celery_app.register_task(ComputeComparisonTask())
compute_comparison_task = celery_app.tasks[RegisteredComputeComparisonTask.name]
