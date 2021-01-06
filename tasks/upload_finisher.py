import logging
import re
from copy import deepcopy

from app import celery_app
from tasks.base import BaseCodecovTask
from database.models import Commit, Pull

from services.redis import get_redis_connection
from services.yaml import read_yaml_field

from celery_config import (
    notify_task_name,
    status_set_pending_task_name,
    pulls_task_name,
)

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

    name = "app.tasks.upload_finisher.UploadFinisherTask"

    async def run_async(
        self, db_session, processing_results, *, repoid, commitid, commit_yaml, **kwargs
    ):
        log.info(
            "Received upload_finisher task",
            extra=dict(
                repoid=repoid, commit=commitid, processing_results=processing_results
            ),
        )
        repoid = int(repoid)
        lock_name = f"upload_finisher_lock_{repoid}_{commitid}"
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        redis_connection = get_redis_connection()
        with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=5):
            db_session.commit()
            commit.notified = False
            db_session.commit()
            result = await self.finish_reports_processing(
                db_session, commit, commit_yaml, processing_results
            )
            self.invalidate_caches(redis_connection, commit)
            if commit.repository.branch == commit.branch:
                author_dict = None
                if commit.author:
                    author_dict = {
                        "service": commit.author.service,
                        "service_id": commit.author.service_id,
                        "username": commit.author.username,
                        "email": commit.author.email,
                        "name": commit.author.name,
                    }
                commit_dict = {
                    "timestamp": commit.timestamp.isoformat()
                    if commit.timestamp
                    else None,
                    "commitid": commit.commitid,
                    "ci_passed": commit.ci_passed,
                    "message": commit.message,
                    "author": author_dict,
                    "totals": commit.totals,
                }
                new_cache = deepcopy(commit.repository.cache_do_not_use) or {}
                new_cache["commit"] = commit_dict
                commit.repository.cache_do_not_use = new_cache
        return result

    async def finish_reports_processing(
        self, db_session, commit, commit_yaml, processing_results
    ):
        log.debug("In finish_reports_processing for commit: %s" % commit)
        commitid = commit.commitid
        repoid = commit.repoid

        # always notify, let the notify handle if it should submit
        notifications_called = False
        if not regexp_ci_skip.search(commit.message or ""):
            if self.should_call_notifications(commit, commit_yaml, processing_results):
                notifications_called = True
                log.info(
                    "Scheduling notify task",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        commit_yaml=commit_yaml,
                        processing_results=processing_results,
                    ),
                )
                self.app.tasks[notify_task_name].apply_async(
                    kwargs=dict(
                        repoid=repoid, commitid=commitid, current_yaml=commit_yaml
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
                                ),
                            )
            else:
                notifications_called = False
                log.info(
                    "Skipping notify task",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        commit_yaml=commit_yaml,
                        processing_results=processing_results,
                    ),
                )
        else:
            commit.state = "skipped"
        return {"notifications_called": notifications_called}

    def should_call_notifications(self, commit, commit_yaml, processing_results):
        if not any(
            x["successful"] for x in processing_results.get("processings_so_far", [])
        ):
            return False
        number_sessions = 0
        if commit.report_json:
            number_sessions = len(commit.report_json.get("sessions", {}))
        after_n_builds = (
            read_yaml_field(commit_yaml, ("codecov", "notify", "after_n_builds")) or 0
        )
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
                ),
            )
            return False
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


RegisteredUploadTask = celery_app.register_task(UploadFinisherTask())
upload_finisher_task = celery_app.tasks[RegisteredUploadTask.name]
