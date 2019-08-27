import logging
import re
from json import loads
from datetime import datetime

from celery import chain

from helpers.config import get_config
from app import celery_app
from tasks.base import BaseCodecovTask
from database.models import Commit, Owner
from services.redis import get_redis_connection
from services.repository import get_repo_provider_service
from services.yaml import merge_yamls, save_repo_yaml_to_database_if_needed
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from tasks.upload_processor import upload_processor_task
from tasks.upload_finisher import upload_finisher_task

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r'\[(ci|skip| |-){3,}\]').search
merged_pull = re.compile(r'.*Merged in [^\s]+ \(pull request \#(\d+)\).*').match

CHUNK_SIZE = 3


class UploadTask(BaseCodecovTask):
    """The first of a series of tasks designed to process an `upload` made by the user

    This task is the first of three tasks, which run whenever a user makes
        an upload to `UploadHandler` (on the main app code)

    - UploadTask
    - UploadProcessorTask
    - UploadFinisherTask

    Each task has a purpose

    - UploadTask (this one)
        - Prepares the ground for the other tasks to run (view it as a compatibility layer between
            the old code and new)
        - Does thinks that only need to happen once per commit, and not per upload,
            like populating commit info and webhooks
    - UploadProcessorTask
        - Process each individual upload the user did (with some possible batching)
    - UploadFinisherTask
        - Does the finishing steps of processing, like deciding what tasks
            to schedule next (notifications)

    Now a little about this individual task.

    UploadTask has a specific purpose, it does all the 'pre-processing', for things that should be
        run outside the individual `upload` context, and is also the starter
        of the other tasks.

    The preprocessing tasks it does are:
        - Populating commit's info, in case this is the first time this commit is uploaded to our
            servers
        - Setup webhooks, in case this is the first time this repo has an upload on our servers
        - Fetch commit yaml from git provider, and possibly store it on the db (in case this
            is a commit on the repo default branch). This yaml is also passed and used on
            the other tasks, so they don't need to fetch it again

    The last thing this task does is schedule the other tasks. It works as a compatibility layer
        because the `UploadHandler` (on the main app code) pushes some important info to
        redis to be read here, and this task already takes all the relevant info from redis
        and pass them directly as parameters to the other tasks, so they don't have to manually
        deal with redis (since celery kind of automatically does the same behavior already)

    On the scheduling, this task does the following logic:
        - After fetching all uploads metadata (from redis), it splits the uploads in chunks of 3.
        - Each chunk goes to a `UploadProcessorTask`, and they are chained (as in `celery chain`)
        - At the end of the celery chain, we add one `UploadFinisherTask`. So after all processing,
            the finisher task does the finishing steps
        - In the end, the tasks are scheduled (sent to celery), and this task finishes

    """
    name = "app.tasks.upload.Upload"

    def write_to_db(self):
        return False

    def lists_of_arguments(self, redis_connection, uploads_list_key):
        """Retrieves a list of arguments from redis on the `uploads_list_key`, parses them
            and feeds them to the processing code.

        This function doesn't go infinite because it keeps emptying the respective key on redis.
        It will only go arbitrrily long if someone else keeps uploading more and more arguments
        to such list

        Args:
            redis_connection (Redis): An instance of a redis connection
            uploads_list_key (str): The key where the list is

        Yields:
            dict: A dict with the parameters to be passed
        """
        log.debug("Fetching arguments from redis %s", uploads_list_key)
        while redis_connection.exists(uploads_list_key):
            arguments = redis_connection.lpop(uploads_list_key)
            if arguments:  # fix race issue https://app.getsentry.com/codecov/v4/issues/126562772/
                yield loads(arguments)

    async def run_async(self, db_session, repoid, commitid, *args, **kwargs):
        repoid = int(repoid)
        lock_name = f"upload_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=30):
            uploads_list_key = 'testuploads/%s/%s' % (repoid, commitid)
            commit = None
            commits = db_session.query(Commit).filter(
                    Commit.repoid == repoid, Commit.commitid == commitid)
            commit = commits.first()
            assert commit, 'Commit not found in database.'
            log.info(
                "Starting processing of report",
                extra=dict(repoid=repoid, commit=commitid)
            )
            was_updated = await self.possibly_update_commit_from_provider_info(db_session, commit)
            was_setup = await self.possibly_setup_webhooks(commit)
            commit_yaml = await self.fetch_commit_yaml_and_possibly_store(commit)
            argument_list = []
            for arguments in self.lists_of_arguments(redis_connection, uploads_list_key):
                argument_list.append(arguments)
            self.schedule_task(commit, commit_yaml, argument_list)
            return {
                'was_setup': was_setup,
                'was_updated': was_updated
            }

    async def fetch_commit_yaml_and_possibly_store(self, commit):
        repository = commit.repository
        repository_service = get_repo_provider_service(repository, commit)
        commit_yaml = await fetch_commit_yaml_from_provider(commit, repository_service)
        save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        return merge_yamls(repository.owner.yaml, repository.yaml, commit_yaml)

    def schedule_task(self, commit, commit_yaml, argument_list):
        chain_to_call = []
        for i in range(0, len(argument_list), CHUNK_SIZE):
            chunk = argument_list[i:i + CHUNK_SIZE]
            if chunk:
                sig = upload_processor_task.signature(
                    args=({},) if i == 0 else (),
                    kwargs=dict(
                        repoid=commit.repoid,
                        commitid=commit.commitid,
                        commit_yaml=commit_yaml,
                        arguments_list=chunk,
                    ),
                )
                chain_to_call.append(sig)
        if chain_to_call:
            finish_sig = upload_finisher_task.signature(
                kwargs=dict(
                    repoid=commit.repoid,
                    commitid=commit.commitid,
                    commit_yaml=commit_yaml
                ),
            )
            chain_to_call.append(finish_sig)
        return chain(*chain_to_call).apply_async()

    async def possibly_setup_webhooks(self, commit):
        repository = commit.repository
        repository_service = get_repo_provider_service(repository, commit)
        repo_data = repository_service.data
        should_post_webhook = (not repo_data['repo']['using_integration']
                               and not repository.hookid and
                               hasattr(repository_service, 'post_webhook'))
        should_post_webhook = False  # Temporarily while we test this

        # try to add webhook
        if should_post_webhook:
            try:
                hook_result = await self.post_webhook(repository_service)
                hookid = hook_result['id']
                log.info("Registered hook %s for repo %s", hookid, repository.repoid)
                repository.hookid = hookid
                repo_data['repo']['hookid'] = hookid
                return True
            except Exception:
                log.exception(
                    'Failed to create project webhook',
                    extra=dict(repoid=repository.repoid, commit=commit.commitid)
                )
        return False

    async def possibly_update_commit_from_provider_info(self, db_session, commit):
        repoid = commit.repoid
        repository = commit.repository
        commitid = commit.commitid
        try:
            repository_service = get_repo_provider_service(repository, commit)
            if not commit.message:
                log.info(
                    "Commit does not have all needed info. Reaching provider to fetch info",
                    extra=dict(repoid=repoid, commit=commitid)
                )
                await self.update_commit_from_provider_info(db_session, repository_service, commit)
                return True
        except Exception:
            log.exception(
                'Could not properly update commit with info from git provider',
                extra=dict(repoid=repoid, commit=commitid)
            )
            raise
        return False

    def get_author_from_commit(self, db_session, service, author_id, username, email, name):
        author = db_session.query(Owner).filter_by(service_id=author_id, service=service).first()
        if author:
            return author
        author = Owner(
            service_id=author_id, service=service,
            username=username, name=name, email=email
        )
        db_session.add(author)
        return author

    async def update_commit_from_provider_info(self, db_session, repository_service, commit):
        """
            Takes the result from the torngit commit details, and updates the commit
            properties with it

        """
        commitid = commit.commitid
        git_commit = await repository_service.get_commit(commitid)

        if git_commit is None:
            log.error(
                'Could not find commit on git provider',
                extra=dict(repoid=commit.repoid, commit=commit.commitid)
            )
        else:
            author_info = git_commit['author']
            commit_author = self.get_author_from_commit(
                db_session, repository_service.service, author_info['id'], author_info['username'],
                author_info['email'], author_info['name']
            )

            # attempt to populate commit.pullid from repository_service if we don't have it
            if not commit.pullid:
                commit.pullid = await repository_service.find_pull_request(
                    commit=commitid,
                    branch=commit.branch)

            # if our records or the call above returned a pullid, fetch it's details
            if commit.pullid:
                commit_updates = await repository_service.get_pull_request(
                    pullid=commit.pullid
                )
                commit.branch = commit_updates['head']['branch']

            commit.message = git_commit['message']
            commit.parent = git_commit['parents'][0]
            commit.merged = False
            commit.author = commit_author
            commit.updatestamp = datetime.now()

            if repository_service.service == 'bitbucket':
                res = merged_pull(git_commit.message)
                if res:
                    pullid = res.groups()[0]
                    pullid = pullid
                    commit.branch = (
                        await
                        repository_service.get_pull_request(pullid)
                    )['base']['branch']
            log.info(
                'Updated commit with info from git provider',
                extra=dict(repoid=commit.repoid, commit=commit.commitid)
            )

    async def post_webhook(self, repository_service):
        """
            Posts to the provider a webhook so we can receive updates from this
            repo
        """
        webhook_url = (
            get_config('setup', 'webhook_url') or get_config('setup', 'codecov_url')
        )
        WEBHOOK_EVENTS = {
            "github": [
                "pull_request", "delete", "push", "public", "status",
                "repository"
            ],
            "github_enterprise": [
                "pull_request", "delete", "push", "public", "status",
                "repository"
            ],
            "bitbucket": [
                "repo:push", "pullrequest:created", "pullrequest:updated",
                "pullrequest:fulfilled", "repo:commit_status_created",
                "repo:commit_status_updated"
            ],
            # https://confluence.atlassian.com/bitbucketserver/post-service-webhook-for-bitbucket-server-776640367.html
            "bitbucket_server": [],
            "gitlab": {
                "push_events": True,
                "issues_events": False,
                "merge_requests_events": True,
                "tag_push_events": False,
                "note_events": False,
                "job_events": False,
                "build_events": True,
                "pipeline_events": True,
                "wiki_events": False
            },
            "gitlab_enterprise": {
                "push_events": True,
                "issues_events": False,
                "merge_requests_events": True,
                "tag_push_events": False,
                "note_events": False,
                "job_events": False,
                "build_events": True,
                "pipeline_events": True,
                "wiki_events": False
            }
        }
        return await repository_service.post_webhook(
            f'Codecov Webhook. {webhook_url}',
            f'{webhook_url}/webhooks/{repository_service.service}',
            WEBHOOK_EVENTS[repository_service.service],
            get_config(
                repository_service.service, 'webhook_secret',
                default='ab164bf3f7d947f2a0681b215404873e')
            )


RegisteredUploadTask = celery_app.register_task(UploadTask())
upload_task = celery_app.tasks[RegisteredUploadTask.name]
