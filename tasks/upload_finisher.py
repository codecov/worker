import logging
import re

from app import celery_app
from tasks.base import BaseCodecovTask
from database.models import Commit

from services.redis import get_redis_connection
from services.yaml import read_yaml_field

from celery_config import notify_task_name, status_set_pending_task_name

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

    def write_to_db(self):
        return True

    async def run_async(self, db_session, processing_results, *, repoid, commitid, commit_yaml, **kwargs):
        log.info(
            "Received upload task",
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

            result = await self.finish_reports_processing(db_session, commit, commit_yaml)
            self.invalidate_caches(redis_connection, commit)
        return result

    async def finish_reports_processing(self, db_session, commit, commit_yaml):
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
            number_sessions = 0
            if commit.report_json:
                number_sessions = len(commit.report_json.get('sessions', {}))
            after_n_builds = read_yaml_field(commit_yaml, ('codecov', 'notify', 'after_n_builds')) or 0
            should_call_notifications = bool(after_n_builds <= number_sessions)
            if should_call_notifications:
                self.app.send_task(
                    notify_task_name,
                    args=None,
                    kwargs=dict(
                        repoid=repoid,
                        commitid=commitid
                    )
                )
        else:
            commit.state = 'skipped'
            commit.notified = False
        return {}

    def invalidate_caches(self, redis_connection, commit):
        redis_connection.delete('cache/{}/tree/{}'.format(commit.repoid, commit.branch))
        redis_connection.delete('cache/{0}/tree/{1}'.format(commit.repoid, commit.commitid))


RegisteredUploadTask = celery_app.register_task(UploadFinisherTask())
upload_finisher_task = celery_app.tasks[RegisteredUploadTask.name]
