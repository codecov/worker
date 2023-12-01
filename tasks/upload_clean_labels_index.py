import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, TypedDict

from redis.exceptions import LockError
from shared.reports.resources import Report
from shared.reports.types import CoverageDatapoint
from shared.torngit.base import TorngitBaseAdapter
from shared.utils.enums import TaskConfigGroup
from shared.yaml import UserYaml

from database.models.core import Commit
from database.models.reports import CommitReport
from services.redis import get_redis_connection
from services.report import ReportService
from services.report.labels_index import LabelsIndexService
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
    commit_report: CommitReport
    commit_yaml: Optional[Dict]


class CleanLabelsIndex(
    BaseCodecovTask,
    name=f"app.tasks.{TaskConfigGroup.upload.value}.UploadCleanLabelsIndex",
):
    async def run_async(
        self, db_session, repoid, commitid, report_code=None, *args, **kwargs
    ):
        redis_connection = get_redis_connection()
        repoid = int(repoid)
        lock_name = UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid)
        if (
            self.is_currently_processing(redis_connection, lock_name)
            and self.request.retries == 0
        ):
            log.info(
                "Currently processing upload. Retrying in 300s.",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    has_pending_jobs=self.has_pending_jobs(
                        redis_connection, repoid, commitid
                    ),
                ),
            )
            _prepare_kwargs_for_retry(repoid, commitid, report_code, kwargs)
            self.retry(countdown=300, kwargs=kwargs)
        # Collect as much info as possible outside the lock
        # so that the time we stay with the lock is as small as possible
        commit = self._get_commit_or_fail(db_session, repoid, commitid)
        commit_report = self._get_commit_report_or_fail(db_session, commit, report_code)
        repository_service = get_repo_provider_service(commit.repository, commit)
        commit_yaml = await self._get_best_effort_commit_yaml(
            commit, repository_service
        )
        read_only_args = ReadOnlyArgs(
            commit=commit, commit_yaml=commit_yaml, commit_report=commit_report
        )
        try:
            with redis_connection.lock(
                UPLOAD_PROCESSING_LOCK_NAME(repoid, commitid),
                timeout=max(300, self.hard_time_limit_task),
                blocking_timeout=5,
            ):
                return await self.run_async_within_lock(
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
        # TODO: retry logic

    async def run_async_within_lock(
        self,
        db_session,
        read_only_args: ReadOnlyArgs,
        *args,
        **kwargs,
    ):
        commit = read_only_args["commit"]
        commit_report = read_only_args["commit_report"]
        log.info(
            "Starting cleanup of labels index",
            extra=dict(
                repoid=commit.repository.repoid,
                commit=commit.commitid,
                report_code=commit_report.code,
            ),
        )

        # Get the report
        report_service = ReportService(read_only_args["commit_yaml"])

        report = report_service.get_existing_report_for_commit(
            commit, report_code=commit_report.code
        )
        if report is None:
            log.error(
                "Report not found",
                extra=dict(commit=commit.commitid, report_code=commit_report.code),
            )
            return {"success": False, "error": "Report not found"}
        # Get the labels index and prep report for changes
        labels_index_service = LabelsIndexService.from_commit_report(commit_report)
        labels_index_service.set_label_idx(report)
        if report.labels_index == dict():
            log.error(
                "Labels index is empty, nothing to do",
                extra=dict(commit=commit.commitid, report_code=commit_report.code),
            )
            return {"success": False, "error": "Labels index is empty, nothing to do"}
        # Make the changes
        self.cleanup_report_labels_index(report)
        # Save changes
        # If one of these operations succeed and the other fail we are TOAST
        # TODO: Create error-recovery mechanism in the Report
        report_service.save_report(report)
        labels_index_service.save_and_unset_label_idx(report)
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

    async def _get_best_effort_commit_yaml(
        self, commit: Commit, repository_service: TorngitBaseAdapter
    ) -> Dict:
        repository = commit.repository
        commit_yaml = None
        if repository_service:
            commit_yaml = await fetch_commit_yaml_from_provider(
                commit, repository_service
            )
        if commit_yaml is None:
            commit_yaml = UserYaml.get_final_yaml(
                owner_yaml=repository.owner.yaml,
                repo_yaml=repository.yaml,
                commit_yaml=None,
                ownerid=repository.owner.ownerid,
            ).to_dict()
        return commit_yaml

    def _get_commit_or_fail(self, db_session, repoid: int, commitid: str) -> Commit:
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."

    def _get_commit_report_or_fail(
        self, db_session, commit: Commit, report_code
    ) -> CommitReport:
        commit_report = (
            db_session.query(CommitReport)
            .filter(commit_id=commit.id, code=report_code)
            .first()
        )
        assert commit_report, "CommitReport not found in database."

    def _is_currently_processing(self, redis_connection, lock_name):
        if redis_connection.get(lock_name):
            return True
        return False
