import json
import logging
import re
from copy import deepcopy

import sentry_sdk
from shared.celery_config import (
    compute_comparison_task_name,
    notify_task_name,
    pulls_task_name,
    upload_finisher_task_name,
)
from shared.yaml import UserYaml

from app import celery_app
from database.models import Commit, Pull
from helpers.checkpoint_logger import UploadFlow, _kwargs_key
from helpers.checkpoint_logger import from_kwargs as checkpoints_from_kwargs
from services.comparison import get_or_create_comparison
from services.redis import get_redis_connection
from services.report import ReportService
from services.timeseries import save_commit_measurements
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r"\[(ci|skip| |-){3,}\]")
merged_pull = re.compile(r".*Merged in [^\s]+ \(pull request \#(\d+)\).*").match


class UploadFinisherTask(BaseCodecovTask):
    """This is the third task of the series of tasks designed to process an `upload` made
    by the user

    To see more about the whole picture, see `tasks.upload.UploadTask`

    This task does the finishing steps after a group of uploads is processed

    The steps are:
        - Schedule the set_pending task, depending on the case
        - Schedule notification tasks, depending on the case
        - Invalidating whatever cache is done
    """

    name = upload_finisher_task_name

    async def run_async(
        self,
        db_session,
        processing_results,
        *,
        repoid,
        commitid,
        commit_yaml,
        report_code=None,
        **kwargs,
    ):
        try:
            checkpoints = checkpoints_from_kwargs(UploadFlow, kwargs)
            checkpoints.log(UploadFlow.BATCH_PROCESSING_COMPLETE).submit_subflow(
                "batch_processing_duration",
                UploadFlow.INITIAL_PROCESSING_COMPLETE,
                UploadFlow.BATCH_PROCESSING_COMPLETE,
            )
        except ValueError as e:
            log.warning(f"CheckpointLogger failed to log/submit", extra=dict(error=e))

        log.info(
            "Received upload_finisher task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                processing_results=processing_results,
                parent_task=self.request.parent_id,
            ),
        )
        repoid = int(repoid)
        lock_name = f"upload_finisher_lock_{repoid}_{commitid}"
        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database."

        def dl(partial_report):
            chunks = archive_service.read_file(partial_report["chunks_path"]).decode(
                errors="replace"
            )
            files_and_sessions = json.loads(
                archive_service.read_file(partial_report["files_sessions_path"])
            )
            return report_service.build_report(
                chunks,
                files_and_sessions["files"],
                files_and_sessions["sessions"],
                None,
            )

        def merge_report(l, r):
            # TODO, this is complicated
            # reference `raw_upload_processor`'s `_adjust_sessions` and `report.merge()`
            pass

        unmerged_reports = (dl(report) for report in processing_results)
        report = functools.reduce(merge_report, unmerged_reports)

        with metrics.timer(f"{self.metrics_prefix}.save_report_results"):
            results_dict = await self.save_report_results(
                db_session,
                report_service,
                repository,
                commit,
                report,
                pr,
                report_code,
            )

        redis_connection = get_redis_connection()
        with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=5):
            commit_yaml = UserYaml(commit_yaml)
            db_session.commit()
            commit.notified = False
            db_session.commit()
            result = await self.finish_reports_processing(
                db_session,
                commit,
                commit_yaml,
                processing_results,
                report_code,
                report,
                checkpoints,
            )
            save_commit_measurements(commit)
            self.invalidate_caches(redis_connection, commit)
        return result

    async def finish_reports_processing(
        self,
        db_session,
        commit,
        commit_yaml: UserYaml,
        processing_results,
        report_code,
        report,
        checkpoints,
    ):
        log.debug("In finish_reports_processing for commit: %s" % commit)
        commitid = commit.commitid
        repoid = commit.repoid

        # always notify, let the notify handle if it should submit
        notifications_called = False
        if not regexp_ci_skip.search(commit.message or ""):
            if self.should_call_notifications(
                commit, commit_yaml, processing_results, report_code, report
            ):
                notifications_called = True
                task = self.app.tasks[notify_task_name].apply_async(
                    kwargs={
                        "repoid": repoid,
                        "commitid": commitid,
                        "current_yaml": commit_yaml.to_dict(),
                        _kwargs_key(UploadFlow): checkpoints.data,
                    },
                )
                log.info(
                    "Scheduling notify task",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        commit_yaml=commit_yaml.to_dict(),
                        processing_results=processing_results,
                        notify_task_id=task.id,
                        parent_task=self.request.parent_id,
                    ),
                )
                if commit.pullid:
                    pull = (
                        db_session.query(Pull)
                        .filter_by(repoid=commit.repoid, pullid=commit.pullid)
                        .first()
                    )
                    if pull:
                        head = pull.get_head_commit()
                        if head is None or head.timestamp <= commit.timestamp:
                            pull.head = commit.commitid
                        if pull.head == commit.commitid:
                            db_session.commit()
                            self.app.tasks[pulls_task_name].apply_async(
                                kwargs=dict(
                                    repoid=repoid,
                                    pullid=pull.pullid,
                                    should_send_notifications=False,
                                )
                            )
                            compared_to = pull.get_comparedto_commit()
                            if compared_to:
                                comparison = get_or_create_comparison(
                                    db_session, compared_to, commit
                                )
                                db_session.commit()
                                self.app.tasks[
                                    compute_comparison_task_name
                                ].apply_async(kwargs=dict(comparison_id=comparison.id))

            else:
                notifications_called = False
                log.info(
                    "Skipping notify task",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        commit_yaml=commit_yaml.to_dict(),
                        processing_results=processing_results,
                        parent_task=self.request.parent_id,
                    ),
                )
        else:
            commit.state = "skipped"

        if checkpoints:
            checkpoints.log(UploadFlow.PROCESSING_COMPLETE).submit_subflow(
                "total_processing_duration",
                UploadFlow.PROCESSING_BEGIN,
                UploadFlow.PROCESSING_COMPLETE,
            )
        return {"notifications_called": notifications_called}

    def should_call_notifications(
        self, commit, commit_yaml, processing_results, report_code, report
    ):
        manual_trigger = read_yaml_field(
            commit_yaml, ("codecov", "notify", "manual_trigger")
        )
        if manual_trigger:
            log.info(
                "Not scheduling notify because manual trigger is used",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    commit_yaml=commit_yaml,
                    processing_results=processing_results,
                ),
            )
            return False
        # Notifications should be off in case of local uploads, and report code wouldn't be null in that case
        if report_code is not None:
            log.info(
                "Not scheduling notify because it's a local upload",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    commit_yaml=commit_yaml,
                    processing_results=processing_results,
                    report_code=report_code,
                    parent_task=self.request.parent_id,
                ),
            )
            return False
        if not any(
            x["successful"] for x in processing_results.get("processings_so_far", [])
        ):
            return False

        after_n_builds = (
            read_yaml_field(commit_yaml, ("codecov", "notify", "after_n_builds")) or 0
        )
        if after_n_builds > 0:
            number_sessions = len(report.sessions) if report is not None else 0
            if after_n_builds > number_sessions:
                log.info(
                    "Not scheduling notify because `after_n_builds` is %s and we only found %s builds",
                    after_n_builds,
                    number_sessions,
                    extra=dict(
                        repoid=commit.repoid,
                        commit=commit.commitid,
                        commit_yaml=commit_yaml,
                        processing_results=processing_results,
                        parent_task=self.request.parent_id,
                    ),
                )
                return False
            else:
                return True
        return True

    def invalidate_caches(self, redis_connection, commit: Commit):
        redis_connection.delete("cache/{}/tree/{}".format(commit.repoid, commit.branch))
        redis_connection.delete(
            "cache/{0}/tree/{1}".format(commit.repoid, commit.commitid)
        )
        repository = commit.repository
        key = ":".join((repository.service, repository.owner.username, repository.name))
        if commit.branch:
            redis_connection.hdel("badge", ("%s:%s" % (key, (commit.branch))).lower())
            if commit.branch == repository.branch:
                redis_connection.hdel("badge", ("%s:" % key).lower())

    async def save_report_results(
        self,
        db_session,
        report_service,
        repository,
        commit,
        report,
        pr,
        report_code=None,
    ):
        """Saves the result of `report` to the commit database and chunks archive

        This method only takes care of getting a processed Report to the database and archive.

        It also tries to calculate the diff of the report (which uses commit info
            from th git provider), but it it fails to do so, it just moves on without such diff
        """
        log.debug("In save_report_results for commit: %s" % commit)
        commitid = commit.commitid
        try:
            repository_service = get_repo_provider_service(repository, commit)
            report.apply_diff(await repository_service.get_commit_diff(commitid))
        except TorngitError:
            # When this happens, we have that commit.totals["diff"] is not available.
            # Since there is no way to calculate such diff without the git commit,
            # then we assume having the rest of the report saved there is better than the
            # alternative of refusing an otherwise "good" report because of the lack of diff
            log.warning(
                "Could not apply diff to report because there was an error fetching diff from provider",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    parent_task=self.request.parent_id,
                ),
                exc_info=True,
            )
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit,
                error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
                error_params=dict(
                    repoid=commit.repoid,
                    pr=pr,
                ),
            )

            log.warning(
                "Could not apply diff to report because there is no valid bot found for that repo",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    parent_task=self.request.parent_id,
                ),
                exc_info=True,
            )
        if pr is not None:
            try:
                commit.pullid = int(pr)
            except (ValueError, TypeError):
                log.warning(
                    "Cannot set PR value on commit",
                    extra=dict(
                        repoid=commit.repoid, commit=commit.commitid, pr_value=pr
                    ),
                )
        res = report_service.save_report(commit, report, report_code)
        db_session.commit()
        return res


RegisteredUploadTask = celery_app.register_task(UploadFinisherTask())
upload_finisher_task = celery_app.tasks[RegisteredUploadTask.name]
