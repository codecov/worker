import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, TypedDict

from asgiref.sync import async_to_sync
from redis.exceptions import LockError
from shared.reports.resources import Report
from shared.reports.types import CoverageDatapoint
from shared.torngit.base import TorngitBaseAdapter
from shared.utils.enums import TaskConfigGroup
from shared.yaml import UserYaml
from shared.yaml.user_yaml import OwnerContext, RepoContext

from app import celery_app
from database.models.core import Commit
from services.redis import get_redis_connection
from services.report import ReportService
from services.repository import get_repo_provider_service
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from tasks.base import BaseCodecovTask
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME

log = logging.getLogger(__name__)


def _prepare_kwargs_for_retry(repoid, commitid, report_code, kwargs):
    kwargs.update(
        {
            "repoid": repoid,
            "commitid": commitid,
            "report_code": report_code,
        }
    )


class ReadOnlyArgs(TypedDict):
    commit: Commit
    report_code: str
    commit_yaml: Optional[Dict]


# TODO: Move to shared
task_name = f"app.tasks.{TaskConfigGroup.upload.value}.UploadCleanLabelsIndex"


class CleanLabelsIndexTask(
    BaseCodecovTask,
    name=task_name,
):
    def run_impl(self, db_session, repoid, commitid, report_code=None, *args, **kwargs):
        redis_connection = get_redis_connection()
        repoid = int(repoid)
        lock_name = UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid)
        if self._is_currently_processing(redis_connection, lock_name):
            log.info(
                "Currently processing upload. Retrying in 300s.",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                ),
            )
            _prepare_kwargs_for_retry(repoid, commitid, report_code, kwargs)
            self.retry(countdown=300, kwargs=kwargs)
        # Collect as much info as possible outside the lock
        # so that the time we stay with the lock is as small as possible
        commit = self._get_commit_or_fail(db_session, repoid, commitid)
        repository_service = get_repo_provider_service(commit.repository)
        commit_yaml = self._get_best_effort_commit_yaml(commit, repository_service)
        read_only_args = ReadOnlyArgs(
            commit=commit, commit_yaml=commit_yaml, report_code=report_code
        )
        try:
            with redis_connection.lock(
                UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid),
                timeout=max(300, self.hard_time_limit_task),
                blocking_timeout=5,
            ):
                return self.run_impl_within_lock(
                    db_session,
                    read_only_args,
                    *args,
                    **kwargs,
                )
        except LockError:
            log.warning(
                "Unable to acquire lock for key %s.",
                lock_name,
                extra=dict(commit=commitid, repoid=repoid),
            )
        retry_countdown = 20 * 2**self.request.retries + 280
        log.warning(
            "Retrying clean labels index task",
            extra=dict(commit=commitid, repoid=repoid, countdown=int(retry_countdown)),
        )
        _prepare_kwargs_for_retry(repoid, commitid, report_code, kwargs)
        self.retry(max_retries=3, countdown=retry_countdown, kwargs=kwargs)

    def run_impl_within_lock(
        self,
        read_only_args: ReadOnlyArgs,
        *args,
        **kwargs,
    ):
        commit = read_only_args["commit"]
        report_code = read_only_args["report_code"]
        log.info(
            "Starting cleanup of labels index",
            extra=dict(
                repoid=commit.repository.repoid,
                commit=commit.commitid,
                report_code=report_code,
            ),
        )

        # Get the report
        report_service = ReportService(read_only_args["commit_yaml"])

        report = report_service.get_existing_report_for_commit(
            commit, report_code=report_code
        )
        if report is None:
            log.error(
                "Report not found",
                extra=dict(commit=commit.commitid, report_code=report_code),
            )
            return {"success": False, "error": "Report not found"}
        # Get the labels index and prep report for changes
        if not report.labels_index:
            log.error(
                "Labels index is empty, nothing to do",
                extra=dict(commit=commit.commitid, report_code=report_code),
            )
            return {"success": False, "error": "Labels index is empty, nothing to do"}
        # Make the changes
        self.cleanup_report_labels_index(report)
        # Save changes
        report_service.save_report(report)
        return {"success": True}

    def cleanup_report_labels_index(self, report: Report):
        used_labels_set: Set[int] = set()
        # This is used later as a reference to the datapoints that might be
        # updated for a given label.
        # it works because it actually saves a reference to the CoverageDatapoint
        # so changing the ref changes the datapoint in the Report
        datapoints_with_label: Dict[int, List[CoverageDatapoint]] = defaultdict(list)

        # Collect all the labels that are being used
        for report_file in report:
            for _, report_line in report_file.lines:
                if report_line.datapoints:
                    for datapoint in report_line.datapoints:
                        for label_id in datapoint.label_ids:
                            used_labels_set.add(label_id)
                            datapoints_with_label[label_id].append(datapoint)

        labels_stored_max_index = max(report.labels_index.keys())
        offset = 0
        # The 0 index is special, let's not touch that.
        # It's important that we iterate in order so that we always replace labels
        # with a SMALLER index
        for label_index in range(1, labels_stored_max_index + 1):
            if label_index in used_labels_set:
                report.labels_index[label_index - offset] = report.labels_index[
                    label_index
                ]
                for datapoint in datapoints_with_label[label_index]:
                    idx_to_change = datapoint.label_ids.index(label_index)
                    datapoint.label_ids[idx_to_change] = label_index - offset
            else:
                # This label is no longer in the report. We can reuse this index
                offset += 1
        # After fixing all indexes we can remove the last 'offset' ones
        while offset:
            del report.labels_index[labels_stored_max_index]
            labels_stored_max_index -= 1
            offset -= 1

    def _get_best_effort_commit_yaml(
        self, commit: Commit, repository_service: TorngitBaseAdapter
    ) -> Dict:
        repository = commit.repository
        commit_yaml = None
        if repository_service:
            commit_yaml = async_to_sync(fetch_commit_yaml_from_provider)(
                commit, repository_service
            )
        if commit_yaml is None:
            owner_context = OwnerContext(
                owner_onboarding_date=repository.owner.createstamp,
                owner_plan=repository.owner.plan,
                ownerid=repository.ownerid,
            )
            repo_context = RepoContext(repo_creation_date=repository.created_at)
            commit_yaml = UserYaml.get_final_yaml(
                owner_yaml=repository.owner.yaml,
                repo_yaml=repository.yaml,
                commit_yaml=None,
                owner_context=owner_context,
                repo_context=repo_context,
            ).to_dict()
        return commit_yaml

    def _get_commit_or_fail(self, db_session, repoid: int, commitid: str) -> Commit:
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        return commit

    def _is_currently_processing(self, redis_connection, lock_name: str):
        if redis_connection.get(lock_name):
            return True
        return False


RegisteredCleanLabelsIndexTask = celery_app.register_task(CleanLabelsIndexTask())
clean_labels_index_task = celery_app.tasks[RegisteredCleanLabelsIndexTask.name]
