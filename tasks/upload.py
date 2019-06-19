import logging
import re
from json import loads, dumps
from time import time
from datetime import datetime
import zlib

import minio.error
from celery import exceptions


from app import celery_app
from tasks.base import BaseCodecovTask
from database.models import Commit, Owner
from services.redis import get_redis_connection
from services.repository import get_repo_provider_service
from services.report import ReportService
from services.archive import ArchiveService, MinioEndpoints
from helpers.config import get_config
from celery_config import notify_task_name, status_set_pending_task_name
from covreports.utils.sessions import Session

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r'\[(ci|skip| |-){3,}\]').search
merged_pull = re.compile(r'.*Merged in [^\s]+ \(pull request \#(\d+)\).*').match


def recursive_getattr(_dict, keys, _else=None):
    try:
        for key in keys:
            if hasattr(_dict, '_asdict'):
                # namedtuples
                _dict = getattr(_dict, key)
            elif hasattr(_dict, '__getitem__'):
                _dict = _dict[key]
            else:
                _dict = getattr(_dict, key)
        return _dict
    except (AttributeError, KeyError):
        return _else


class UploadTask(BaseCodecovTask):
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
        log.info("Fetching arguments from redis %s", uploads_list_key)
        while redis_connection.exists(uploads_list_key):
            arguments = redis_connection.lpop(uploads_list_key)
            if arguments:  # fix race issue https://app.getsentry.com/codecov/v4/issues/126562772/
                yield loads(arguments)

    def acquire_lock(self, redis_connection, repoid, commitid):
        log.info("In acquire_lock for commit:%s" % commitid)
        key = '%s/%s' % (repoid, commitid)
        if redis_connection.sismember('processing/upload', key):
            log.info("Commitid %s already in the processing queue", commitid)
            return False
        log.info("Commitid %s already in the processing queue", commitid)
        redis_connection.sadd('processing/upload', key)
        return True

    def release_lock(self, redis_connection, repoid, commitid):
        return redis_connection.srem('processing/upload', '%s/%s' % (repoid, commitid))

    def schedule_for_later_try(self, redis_connection, uploads_list_key, try_later_list):
        log.info("Scheduling %s reports to be processed later", len(try_later_list))
        retry_in = 20 * (self.request.retries + 1)
        for el_to_try_later in try_later_list:
            redis_connection.rpush(uploads_list_key, dumps(el_to_try_later))
        self.retry(max_retries=3, countdown=retry_in)

    async def run_async(self, db_session, repoid, commitid, *args, **kwargs):
        log.info("In run_async for commit: %s" % commitid)
        redis_connection = get_redis_connection()
        if not self.acquire_lock(redis_connection, repoid, commitid):
            return {}
        uploads_list_key = 'testuploads/%s/%s' % (repoid, commitid)
        commit = None
        n_processed = 0
        commits = db_session.query(Commit).filter(
                Commit.repoid == repoid, Commit.commitid == commitid)
        commit = commits.first()
        assert commit, 'Commit not found in database.'
        repository = commit.repository
        try:
            log.info("Starting processing of report for commit %s", commitid)
            repository_service = get_repo_provider_service(repository, commit)
            archive_service = ArchiveService(repository)
            if not commit.message:
                log.info(
                    "Commit %s from repo %s does not have all needed info. Reaching provider to fetch info",
                    commitid, repoid
                )
                await self.update_commit_from_provider_info(db_session, repository_service, commit)

            report = ReportService().build_report_from_commit(commit)

            pr = None

            should_delete_archive = self.should_delete_archive(
                repository_service, commit.repository
            )

            try_later = []

            for arguments in self.lists_of_arguments(redis_connection, uploads_list_key):
                pr = arguments.get('pr')
                log.info("Running from arguments %s", arguments)
                try:
                    log.info("Processing report for commit %s with arguments %s", commitid, arguments)
                    report = await self.process_individual_report(
                        archive_service, redis_connection, repository_service, commit, report,
                        should_delete_archive, **arguments)
                except Exception:
                    log.exception("Could not process commit %s with parameters %s", commitid, arguments)
                    try_later.append(arguments)
                n_processed += 1

            log.info('Processed %d reports for commit %s on repo %s', n_processed, commitid, repoid)

            self.release_lock(redis_connection, repoid, commitid)
            if n_processed > 0:
                return await self.finish_reports_processing(
                    db_session, archive_service, redis_connection, repository_service,
                    repository, commit, report, pr
                )
            if try_later:
                self.schedule_for_later_try(redis_connection, uploads_list_key, try_later)
        except exceptions.Retry:
            raise
        except Exception:
            commit.state = 'error'
            log.exception('Could not properly upload commit %s - %s', repoid, commitid)
            raise
        finally:
            self.release_lock(redis_connection, repoid, commitid)
            log.info('Finished processing for commit %s on repoid %s', repoid, commitid)

    async def finish_reports_processing(
            self, db_session, archive_service, redis_connection,
            repository_service, repository, commit, report, pr):
        log.debug("In finish_reports_processing for commit: %s" % commit)
        commitid = commit.commitid
        repoid = commit.repoid
        report.apply_diff(await repository_service.get_commit_diff(commitid))

        write_archive_service = ArchiveService(commit.repository, bucket='testingarchive')
        self.save_report(write_archive_service, redis_connection, commit, report, pullid=pr)
        db_session.flush()
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
        branchs_considered_for_yaml = (
            repository_service.data['repo'].get('strict_yaml_branch'),
            commit.repository.branch,
            recursive_getattr(repository_service.data['yaml'], ('codecov', 'branch'))
        )
        if commit.branch and commit.branch in branchs_considered_for_yaml:
            syb = repository_service.data['repo'].get('strict_yaml_branch')
            if not syb or (syb and syb == commit.branch):
                # update yaml cache
                yaml_branch = recursive_getattr(repository_service.data['yaml'], ('codecov', 'branch'))
                if repository_service.data['_yaml_location'] and yaml_branch:
                    repository.branch = recursive_getattr(repository_service.data['yaml'], ('codecov', 'branch'))
                if repository_service.data['_yaml_location'] and yaml_branch:
                    repository.yaml = recursive_getattr(repository_service.data['yaml'], ('codecov', 'branch'))
                log.info('Updated project yaml cache on commit %s', commit.commitid)

        # delete branch cache
        self.invalidate_caches(redis_connection, commit)
        repo_data = repository_service.data

        should_post_webhook = (not repo_data['repo']['using_integration']
                               and not repository.hookid and
                               hasattr(repository_service, 'post_webhook'))
        should_post_webhook = False

        # try to add webhook
        if should_post_webhook:
            try:
                hook_result = await self.post_webhook(repository_service)
                hookid = hook_result['id']
                log.info("Registered hook %s for repo %s", hookid, repoid)
                repository.hookid = hookid
                repo_data['repo']['hookid'] = hookid
            except Exception:
                log.exception('Failed to create project webhook')

        # always notify, let the notify handle if it should submit
        if not regexp_ci_skip(commit.message or ''):
            if (report and (recursive_getattr(repo_data['yaml'], ('codecov', 'notify', 'after_n_builds'))
                            or 0) <= len(report.sessions)):
                # we have the right number of builds
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
        _, report_dict = report.to_database()
        return loads(report_dict)

    async def process_individual_report(
            self, archive_service, redis_connection, repository_service,
            commit, current_report, should_delete_archive, *,
            flags=None, service=None, build_url=None,
            build=None, job=None, name=None, url=None,
            redis_key=None, reportid=None, **kwargs):
        """Takes a `current_report (Report)`, runs a raw_uploaded_report (str) against
            it and generates a new report with the result
        """
        log.info("In process_individual_report for commit: %s" % commit)
        raw_uploaded_report = None
        flags = (flags.split(',') if flags else None)

        archive_url = url
        raw_uploaded_report = self.fetch_raw_uploaded_report(
            archive_service, redis_connection, archive_url, commit.commitid, reportid, redis_key)
        log.info('Retrieved report for processing from url %s', archive_url)

        # delete from archive is desired
        if should_delete_archive and archive_url and not archive_url.startswith('http'):
            archive_service.delete_file(archive_url)
            archive_url = None

        # ---------------
        # Process Reports
        # ---------------
        session = Session(
            provider=service,
            build=build,
            job=job,
            name=name,
            time=int(time()),
            flags=flags,
            archive=archive_url or url,
            url=build_url
        )
        report = self.process_raw_upload(
            repository_service=repository_service,
            master=current_report,
            reports=raw_uploaded_report,
            flags=flags,
            session=session
        )

        log.info(
            'Successfully processed report for session %s and ci %s',
            session.id,
            f'{session.provider}:{session.build}:{session.job}'
        )
        return report

    def save_report(self, archive_service, redis_connection, commit, report, pullid=None):
        totals, network_json_str = report.to_database()
        network = loads(network_json_str)

        if pullid is not None:
            commit.pullid = pullid

        commit.state = 'complete' if report else 'error'
        commit.totals = totals
        commit.report = network

        # ------------------------
        # Archive Processed Report
        # ------------------------
        archive_data = report.to_archive().encode()
        url = archive_service.write_chunks(commit.commitid, archive_data)
        log.info('Archived report on url %s', url)

    def process_raw_upload(self, repository_service, master, reports, flags, session=None):
        return ReportService().build_report_from_raw_content(
            repository_service, master, reports, flags, session
        )

    def fetch_raw_uploaded_report(
            self, archive_service, redis_connection, archive_url, commit_sha, reportid, redis_key):
        """Downloads the raw report, wherever it is (it's either a pth on minio or redis)

        Args:
            archive_service: [description]
            redis_connection: [description]
            archive_url: [description]
            commit_sha: [description]
            reportid: [description]
            redis_key: [description]
        """
        log.info("In fetch_raw_uploaded_report for commit: %s" % commit_sha)
        if archive_url:
            try:
                return archive_service.read_file(archive_url)
            except minio.error.NoSuchKey:
                log.exception("File could not be found on %s for commit %s", archive_url, commit_sha)
                raise
        else:
            return self.download_archive_from_redis(
                archive_service, redis_connection, commit_sha, reportid, redis_key)

    def download_archive_from_redis(
            self, archive_service, redis_connection, commit_sha, reportid, redis_key):
        # download from redis
        raw_uploaded_report = redis_connection.get(redis_key)
        gzipped = redis_key.endswith('/gzip')

        path = MinioEndpoints.raw.get_path(
            date=datetime.now().strftime('%Y-%m-%d'),
            repo_hash=ArchiveService.get_archive_hash(self.repository),
            commit_sha=commit_sha,
            reportid=reportid
        )

        archive_service.write_file(path, raw_uploaded_report, gzipped=gzipped)
        # delete from redis
        redis_connection.delete(redis_key)

        if gzipped:
            raw_uploaded_report = zlib.decompress(
                raw_uploaded_report, zlib.MAX_WBITS | 16
            )
        return raw_uploaded_report

    def should_delete_archive(self, repository_service, repository):
        if get_config('services', 'minio', 'expire_raw_after_n_days'):
            return True
        return not recursive_getattr(
            repository_service.data['yaml'],
            ('codecov', 'archive', 'uploads'),
            _else=True
        )

    def get_author_from_commit(self, db_session, service, author_id, username, email, name):
        author = db_session.query(Owner).filter_by(service_id=author_id, service=service).first()
        if author:
            return author
        author = Owner(
            service_id=author_id, service=service,
            username=username, name=name, email=email
        )
        db_session.add(author)
        db_session.flush()
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
                'Could not find commit in service for commit %s on repo %s.',
                commit.commitid, commit.repoid
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

    def invalidate_caches(self, redis_connection, commit):
        redis_connection.delete('cache/{}/tree/{}'.format(commit.repoid, commit.branch))
        redis_connection.delete('cache/{0}/tree/{1}'.format(commit.repoid, commit.commitid))

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
