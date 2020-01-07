import logging
import re
import random
import os

from app import celery_app
from tasks.base import BaseCodecovTask
from database.models import Commit

from services.redis import get_redis_connection
from services.yaml import read_yaml_field

from celery_config import notify_task_name, status_set_pending_task_name, task_default_queue

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r'\[(ci|skip| |-){3,}\]')
merged_pull = re.compile(r'.*Merged in [^\s]+ \(pull request \#(\d+)\).*').match


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

    async def run_async(self, db_session, processing_results, *, repoid, commitid, commit_yaml, **kwargs):
        log.info(
            "Received upload_finisher task",
            extra=dict(
                repoid=repoid,
                commit=commitid,
                processing_results=processing_results
            )
        )
        repoid = int(repoid)
        lock_name = f"upload_finisher_lock_{repoid}_{commitid}"
        commits = db_session.query(Commit).filter(
                    Commit.repoid == repoid, Commit.commitid == commitid)
        commit = commits.first()
        assert commit, 'Commit not found in database.'
        redis_connection = get_redis_connection()
        with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=30):
            result = await self.finish_reports_processing(db_session, commit, commit_yaml, processing_results)
            self.invalidate_caches(redis_connection, commit)
        return result

    async def finish_reports_processing(self, db_session, commit, commit_yaml, processing_results):
        log.debug("In finish_reports_processing for commit: %s" % commit)
        commitid = commit.commitid
        repoid = commit.repoid
        should_set_pending = self.request.retries == 0

        if should_set_pending:
            self.app.send_task(
                status_set_pending_task_name,
                args=None,
                kwargs=dict(
                    repoid=repoid,
                    commitid=commitid,
                    branch=commit.branch,
                    on_a_pull_request=bool(commit.pullid)
                )
            )

        # always notify, let the notify handle if it should submit
        if not regexp_ci_skip.search(commit.message or ''):
            if self.should_call_notifications(commit, commit_yaml, processing_results):
                notifications_called = True
                log.info(
                    "Scheduling notify task",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        commit_yaml=commit_yaml,
                        processing_results=processing_results
                    )
                )
                if self.should_send_notify_task_to_new_worker(commit):
                    log.info(
                        "Sending task to new worker notify",
                        extra=dict(
                            repoid=repoid,
                            commitid=commitid,
                        )
                    )
                    self.app.tasks[notify_task_name].apply_async(
                        queue=task_default_queue,
                        kwargs=dict(
                            repoid=repoid,
                            commitid=commitid,
                            current_yaml=commit_yaml
                        )
                    )
                else:
                    log.info(
                        "Sending task to legacy worker notify",
                        extra=dict(
                            repoid=repoid,
                            commitid=commitid,
                        )
                    )
                    self.app.send_task(
                        notify_task_name,
                        args=None,
                        kwargs=dict(
                            repoid=repoid,
                            commitid=commitid
                        )
                    )
            else:
                notifications_called = False
                log.info(
                    "Skipping notify task",
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        commit_yaml=commit_yaml,
                        processing_results=processing_results
                    )
                )
        else:
            commit.state = 'skipped'
            commit.notified = False
        return {'notifications_called': notifications_called}

    def should_send_notify_task_to_new_worker(self, commit):
        available_owners = [int(x.strip()) for x in os.getenv('NOTIFY_WHITELISTED_REPOS', '').split()]
        if commit.repoid in available_owners:
            return True
        return random.random() < float(os.getenv('NOTIFY_PERCENTAGE', '0.00'))

    def should_call_notifications(self, commit, commit_yaml, processing_results):
        if not any(x['successful'] for x in processing_results.get('processings_so_far', [])):
            return False
        number_sessions = 0
        if commit.report_json:
            number_sessions = len(commit.report_json.get('sessions', {}))
        after_n_builds = read_yaml_field(commit_yaml, ('codecov', 'notify', 'after_n_builds')) or 0
        if after_n_builds > number_sessions:
            log.info(
                "Not scheduling notify because `after_n_builds` is %s and we only found %s builds",
                after_n_builds, number_sessions,
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    commit_yaml=commit_yaml,
                    processing_results=processing_results
                )
            )
            return False
        return True

    def invalidate_caches(self, redis_connection, commit):
        redis_connection.delete('cache/{}/tree/{}'.format(commit.repoid, commit.branch))
        redis_connection.delete('cache/{0}/tree/{1}'.format(commit.repoid, commit.commitid))


RegisteredUploadTask = celery_app.register_task(UploadFinisherTask())
upload_finisher_task = celery_app.tasks[RegisteredUploadTask.name]
