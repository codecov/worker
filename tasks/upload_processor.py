from json import loads
from time import time
import logging
import re

import minio.error
from celery.exceptions import CeleryError, SoftTimeLimitExceeded
from covreports.utils.sessions import Session
from redis.exceptions import LockError
from sqlalchemy.exc import SQLAlchemyError
from torngit.exceptions import TorngitClientError

from app import celery_app
from celery_config import task_default_queue
from database.models import Commit
from helpers.config import get_config
from helpers.exceptions import ReportExpiredException, ReportEmptyError
from services.archive import ArchiveService
from services.bots import RepositoryWithoutValidBotError
from services.redis import get_redis_connection, download_archive_from_redis
from services.report import ReportService
from services.repository import get_repo_provider_service
from services.storage.exceptions import FileNotInStorageError
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

regexp_ci_skip = re.compile(r'\[(ci|skip| |-){3,}\]').search
merged_pull = re.compile(r'.*Merged in [^\s]+ \(pull request \#(\d+)\).*').match
FIRST_RETRY_DELAY = 20


class UploadProcessorTask(BaseCodecovTask):
    """This is the second task of the series of tasks designed to process an `upload` made
    by the user

    To see more about the whole picture, see `tasks.upload.UploadTask`

    This task processes each user `upload`, and saves the results to db and minio storage

    The steps are:
        - Fetching the user uploaded report (from minio, or sometimes redis)
        - Running them through the language processors, and obtaining reports from that
        - Merging the generated reports to the already existing commit processed reports
        - Saving all that info to the database

    This task doesn't limit how many individual reports it receives for processing. It deals
        with as many as possible. But it is not expected that this task will receive a big
        number of `uploads` to be processed
    """
    name = "app.tasks.upload_processor.UploadProcessorTask"

    def write_to_db(self):
        return True

    def schedule_for_later_try(self):
        retry_in = FIRST_RETRY_DELAY * 3 ** self.request.retries
        self.retry(max_retries=5, countdown=retry_in, queue=task_default_queue)

    async def run_async(self, db_session, previous_results, *, repoid, commitid, commit_yaml, arguments_list, **kwargs):
        repoid = int(repoid)
        log.debug("In run_async for repoid %d and commit %s", repoid, commitid)
        lock_name = f"upload_processing_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(lock_name, timeout=60 * 5, blocking_timeout=30):
                return await self.process_async_within_lock(
                    db_session=db_session,
                    redis_connection=redis_connection,
                    previous_results=previous_results,
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    arguments_list=arguments_list,
                    **kwargs
                )
        except LockError:
            log.warning(
                "Unable to acquire lock for key %s. Retrying", lock_name,
                extra=dict(commit=commitid, repoid=repoid)
            )
            self.schedule_for_later_try()

    async def process_async_within_lock(self, *, db_session, redis_connection, previous_results, repoid, commitid, commit_yaml, arguments_list, **kwargs):
        log.debug("Obtained lock for repoid %d and commit %s", repoid, commitid)
        processings_so_far = previous_results.get('processings_so_far', [])
        commit = None
        n_processed = 0
        commits = db_session.query(Commit).filter(
                Commit.repoid == repoid, Commit.commitid == commitid)
        commit = commits.first()
        assert commit, 'Commit not found in database.'
        repository = commit.repository
        pr = None
        should_delete_archive = self.should_delete_archive(commit_yaml)
        try_later = []
        archive_service = ArchiveService(repository)
        try:
            report = ReportService().build_report_from_commit(
                commit, chunks_archive_service=archive_service
            )
        except Exception:
            log.exception(
                "Unable to fetch current report for commit",
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    arguments_list=arguments_list,
                    commit_yaml=commit_yaml
                )
            )
            raise
        try:
            for arguments in arguments_list:
                pr = arguments.get('pr')
                log.info(
                    "Processing individual report %s", arguments.get('reportid'),
                    extra=dict(repoid=repoid, commit=commitid, arguments=arguments)
                )
                individual_info = {
                    'arguments': arguments.copy()
                }
                try:
                    arguments_commitid = arguments.pop('commit', None)
                    if arguments_commitid:
                        assert arguments_commitid == commit.commitid
                    result = self.process_individual_report(
                        archive_service, redis_connection, commit_yaml,
                        commit, report, should_delete_archive, **arguments
                    )
                    individual_info.update(result)
                except (CeleryError, SoftTimeLimitExceeded):
                    raise
                except SQLAlchemyError:
                    raise
                except Exception:
                    log.exception(
                        "Unable to process report %s", arguments.get('reportid'),
                        extra=dict(
                            commit_yaml=commit_yaml,
                            repoid=repoid,
                            commit=commitid,
                            arguments=arguments
                        )
                    )
                    self.schedule_for_later_try()
                if individual_info.get('successful'):
                    report = individual_info.pop('report')
                    n_processed += 1
                processings_so_far.append(individual_info)
            if n_processed > 0:
                log.info(
                    'Finishing the processing of %d reports',
                    n_processed,
                    extra=dict(repoid=repoid, commit=commitid)
                )
                results_dict = await self.save_report_results(
                    db_session, archive_service,
                    repository, commit, report, pr
                )
                log.info(
                    'Processed %d reports',
                    n_processed,
                    extra=dict(
                        repoid=repoid,
                        commit=commitid,
                        commit_yaml=commit_yaml,
                        url=results_dict.get('url')
                    )
                )
            return {
                'processings_so_far': processings_so_far,
            }
        except CeleryError:
            raise
        except Exception:
            commit.state = 'error'
            log.exception(
                'Could not properly process commit',
                extra=dict(
                    repoid=repoid,
                    commit=commitid,
                    arguments=try_later
                )
            )
            raise

    def process_individual_report(
            self, archive_service, redis_connection, commit_yaml,
            commit, report, *args, **arguments):
        try:
            result = self.do_process_individual_report(
                archive_service, redis_connection, commit_yaml, commit, report, *args, **arguments
            )
            return {
                'successful': True,
                'report': result
            }
        except ReportExpiredException:
            return {
                'successful': False,
                'report': None,
                'error_type': 'report_expired',
                'should_retry': False
            }
        except ReportEmptyError:
            return {
                'successful': False,
                'report': None,
                'error_type': 'report_empty',
                'should_retry': False
            }
        except FileNotInStorageError:
            if self.request.retries == 0:
                log.info(
                    "Scheduling a retry so the file has an extra %d to arrive",
                    FIRST_RETRY_DELAY,
                    extra=dict(
                        repoid=commit.repoid,
                        commit=commit.commitid,
                        arguments=arguments
                    )
                )
                self.schedule_for_later_try()
            log.info(
                "File did not arrive within the expected time, skipping it",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                    arguments=arguments
                )
            )
            return {
                'successful': False,
                'report': None,
                'error_type': 'file_not_in_storage',
                'should_retry': False
            }

    def do_process_individual_report(
            self, archive_service, redis_connection,
            commit_yaml, commit, current_report, should_delete_archive, *,
            flags=None, service=None, build_url=None,
            build=None, job=None, name=None, url=None,
            redis_key=None, reportid=None, **kwargs):
        """Takes a `current_report (Report)`, runs a raw_uploaded_report (str) against
            it and generates a new report with the result
        """
        raw_uploaded_report = None
        flags = (flags.split(',') if flags else None)

        archive_url = url
        raw_uploaded_report = self.fetch_raw_uploaded_report(
            archive_service, redis_connection, archive_url, commit.commitid, reportid, redis_key)
        log.debug('Retrieved report for processing from url %s', archive_url)
        if redis_key and not raw_uploaded_report:
            log.error(
                "Report is not available on redis",
                extra=dict(
                    commit=commit.commitid, repo=commit.repoid
                )
            )

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
            commit_yaml=commit_yaml,
            master=current_report,
            reports=raw_uploaded_report,
            flags=flags,
            session=session
        )

        log.info(
            'Successfully processed report',
            extra=dict(
                session=session.id,
                ci=f'{session.provider}:{session.build}:{session.job}',
                repoid=commit.repoid,
                commit=commit.commitid,
                reportid=reportid,
                commit_yaml=commit_yaml
            )
        )
        return report

    def process_raw_upload(self, commit_yaml, master, reports, flags, session=None):
        return ReportService().build_report_from_raw_content(
            commit_yaml, master, reports, flags, session
        )

    def fetch_raw_uploaded_report(
            self, archive_service, redis_connection, archive_url, commit_sha, reportid, redis_key):
        """
            Downloads the raw report, wherever it is (it's either a path on minio or redis)

        Args:
            archive_service: [description]
            redis_connection: [description]
            archive_url: [description]
            commit_sha: [description]
            reportid: [description]
            redis_key: [description]
        """
        log.debug("In fetch_raw_uploaded_report for commit: %s" % commit_sha)
        if archive_url:
            try:
                return archive_service.read_file(archive_url)
            except minio.error.NoSuchKey:
                log.exception(
                    "File could not be found on %s for commit %s", archive_url, commit_sha
                )
                raise
        else:
            return download_archive_from_redis(redis_connection, redis_key)

    def should_delete_archive(self, commit_yaml):
        if get_config('services', 'minio', 'expire_raw_after_n_days'):
            return True
        return not read_yaml_field(
            commit_yaml,
            ('codecov', 'archive', 'uploads'),
            _else=True
        )

    async def save_report_results(
            self, db_session, chunks_archive_service, repository, commit, report, pr):
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
        except TorngitClientError:
            # When this happens, we have that commit.totals["diff"] is not available.
            # Since there is no way to calculate such diff without the git commit,
            # then we assume having the rest of the report saved there is better than the
            # alternative of refusing an otherwise "good" report because of the lack of diff
            log.warning(
                "Could not apply diff to report because there was a 4xx error",
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid,
                ),
                exc_info=True
            )
        except RepositoryWithoutValidBotError:
            log.warning(
                'Could not apply diff to report because there is no valid bot found for that repo',
                extra=dict(
                    repoid=commit.repoid,
                    commit=commit.commitid
                ),
                exc_info=True
            )
        totals, network_json_str = report.to_database()
        network = loads(network_json_str)

        if pr is not None:
            commit.pullid = pr

        commit.state = 'complete' if report else 'error'
        commit.totals = totals
        commit.report_json = network

        # ------------------------
        # Archive Processed Report
        # ------------------------
        archive_data = report.to_archive().encode()
        url = chunks_archive_service.write_chunks(commit.commitid, archive_data)
        log.info(
            'Archived report',
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
                url=url
            )
        )
        return {
            'url': url
        }


RegisteredUploadTask = celery_app.register_task(UploadProcessorTask())
upload_processor_task = celery_app.tasks[RegisteredUploadTask.name]
