import logging
from typing import Any, Dict

from asgiref.sync import async_to_sync
from shared.celery_config import notify_task_name
from shared.yaml import UserYaml

from app import celery_app
from database.enums import ReportType
from database.models import Commit
from services.bundle_analysis import Notifier
from services.lock_manager import LockManager, LockRetry, LockType
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

bundle_analysis_notify_task_name = "app.tasks.bundle_analysis.BundleAnalysisNotify"


class BundleAnalysisNotifyTask(BaseCodecovTask, name=bundle_analysis_notify_task_name):
    def run_impl(
        self,
        db_session,
        # Celery `chain` injects this argument - it's the returned result
        # from the prior task in the chain
        previous_result: Dict[str, Any],
        *,
        repoid: int,
        commitid: str,
        commit_yaml: dict,
        **kwargs,
    ):
        repoid = int(repoid)
        commit_yaml = UserYaml.from_dict(commit_yaml)

        log.info(
            "Starting bundle analysis notify",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
            ),
        )

        lock_manager = LockManager(
            repoid=repoid,
            commitid=commitid,
            report_type=ReportType.BUNDLE_ANALYSIS,
        )

        try:
            with lock_manager.locked(
                LockType.BUNDLE_ANALYSIS_NOTIFY,
                retry_num=self.request.retries,
            ):
                return self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    previous_result=previous_result,
                    **kwargs,
                )
        except LockRetry as retry:
            self.retry(max_retries=5, countdown=retry.countdown)

    def process_impl_within_lock(
        self,
        *,
        db_session,
        repoid: int,
        commitid: str,
        commit_yaml: UserYaml,
        previous_result: Dict[str, Any],
        **kwargs,
    ):
        log.info(
            "Running bundle analysis notify",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                parent_task=self.request.parent_id,
            ),
        )

        commit = (
            db_session.query(Commit).filter_by(repoid=repoid, commitid=commitid).first()
        )
        assert commit, "commit not found"

        notify = True

        # these are the task results from prior processor tasks in the chain
        # (they get accumulated as we execute each task in succession)
        processing_results = previous_result.get("results", [])

        if all((result["error"] is not None for result in processing_results)):
            # every processor errored, nothing to notify on
            notify = False

        success = None
        if notify:
            notifier = Notifier(commit, commit_yaml)
            success = async_to_sync(notifier.notify)()

        log.info(
            "Finished bundle analysis notify",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                commit_yaml=commit_yaml,
                parent_task=self.request.parent_id,
            ),
        )

        return {"notify_attempted": notify, "notify_succeeded": success}


RegisteredBundleAnalysisNotifyTask = celery_app.register_task(
    BundleAnalysisNotifyTask()
)
bundle_analysis_notify_task = celery_app.tasks[RegisteredBundleAnalysisNotifyTask.name]
