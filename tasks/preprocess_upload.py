import logging
from typing import Optional

from asgiref.sync import async_to_sync
from redis.exceptions import LockError
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError
from shared.validation.exceptions import InvalidYamlException
from shared.yaml import UserYaml
from shared.yaml.user_yaml import OwnerContext

from app import celery_app
from database.enums import CommitErrorTypes
from database.models import Commit
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.save_commit_error import save_commit_error
from services.redis import get_redis_connection
from services.report import ReportService
from services.repository import (
    get_repo_provider_service,
    possibly_update_commit_from_provider_info,
)
from services.yaml import save_repo_yaml_to_database_if_needed
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class PreProcessUpload(BaseCodecovTask, name="app.tasks.upload.PreProcessUpload"):

    """
    The main goal for this task is to carry forward flags from previous uploads
    and save the new carried-forawrded upload in the db,as a pre-step for
    uploading a report to codecov
    """

    def run_impl(
        self,
        db_session,
        *,
        repoid: int,
        commitid: str,
        report_code: Optional[str] = None,
        **kwargs,
    ):
        log.info(
            "Received preprocess upload task",
            extra=dict(repoid=repoid, commit=commitid, report_code=report_code),
        )
        lock_name = f"preprocess_upload_lock_{repoid}_{commitid}_{report_code}"
        redis_connection = get_redis_connection()
        # This task only needs to run once per commit (per report_code)
        # To generate the report. So if one is already running we don't need another
        if self._is_running(redis_connection, lock_name):
            log.info(
                "PreProcess task is already running",
                extra=dict(commit=commitid, repoid=repoid),
            )
            return {"preprocessed_upload": False, "reason": "already_running"}
        try:
            with redis_connection.lock(
                lock_name,
                timeout=60 * 5,
                blocking_timeout=None,
            ):
                return self.process_impl_within_lock(
                    db_session=db_session,
                    repoid=repoid,
                    commitid=commitid,
                    report_code=report_code,
                    **kwargs,
                )
        except LockError:
            log.warning(
                "Unable to acquire lock",
                extra=dict(
                    commit=commitid,
                    repoid=repoid,
                    number_retries=self.request.retries,
                    lock_name=lock_name,
                ),
            )
            return {"preprocessed_upload": False, "reason": "unable_to_acquire_lock"}

    def _is_running(self, redis_connection, lock_name):
        if redis_connection.get(lock_name):
            return True
        return False

    def process_impl_within_lock(
        self,
        *,
        db_session,
        repoid,
        commitid,
        report_code,
        **kwargs,
    ):
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."

        repository_service = self.get_repo_service(commit)
        if repository_service is None:
            log.warning(
                "Failed to get repository_service",
                extra=dict(commit=commitid, repo=repoid),
            )
            return {
                "preprocessed_upload": False,
                "updated_commit": False,
                "error": "Failed to get repository_service",
            }
        # Makes sure that we can properly carry forward reports
        # By populating the commit info (if needed)
        updated_commit = async_to_sync(possibly_update_commit_from_provider_info)(
            commit=commit, repository_service=repository_service
        )
        commit_yaml = self.fetch_commit_yaml_and_possibly_store(
            commit, repository_service
        )
        report_service = ReportService(commit_yaml)
        # For parallel upload processing experiment, saving the report to GCS happens here
        commit_report = async_to_sync(report_service.initialize_and_save_report)(
            commit, report_code
        )
        # Persist changes from within the lock
        db_session.flush()
        return {
            "preprocessed_upload": True,
            "reportid": str(commit_report.external_id),
            "updated_commit": updated_commit,
        }

    def get_repo_service(self, commit) -> Optional[TorngitBaseAdapter]:
        repository_service = None
        try:
            repository_service = get_repo_provider_service(commit.repository, commit)
        except RepositoryWithoutValidBotError:
            save_commit_error(
                commit,
                error_code=CommitErrorTypes.REPO_BOT_INVALID.value,
                error_params=dict(
                    repoid=commit.repoid, repository_service=repository_service
                ),
            )
            log.warning(
                "Unable to reach git provider because repo doesn't have a valid bot",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )

        return repository_service

    def fetch_commit_yaml_and_possibly_store(self, commit, repository_service):
        repository = commit.repository
        try:
            log.info(
                "Fetching commit yaml from provider for commit",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            commit_yaml = async_to_sync(fetch_commit_yaml_from_provider)(
                commit, repository_service
            )
            save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        except InvalidYamlException as ex:
            save_commit_error(
                commit,
                error_code=CommitErrorTypes.INVALID_YAML.value,
                error_params=dict(
                    repoid=repository.repoid,
                    commit=commit.commitid,
                    error_location=ex.error_location,
                ),
            )
            log.warning(
                "Unable to use yaml from commit because it is invalid",
                extra=dict(
                    repoid=repository.repoid,
                    commit=commit.commitid,
                    error_location=ex.error_location,
                ),
                exc_info=True,
            )
            commit_yaml = None
        except TorngitClientError:
            log.warning(
                "Unable to use yaml from commit because it cannot be fetched",
                extra=dict(repoid=repository.repoid, commit=commit.commitid),
                exc_info=True,
            )
            commit_yaml = None
        context = OwnerContext(
            owner_onboarding_date=repository.owner.createstamp,
            owner_plan=repository.owner.plan,
            ownerid=repository.ownerid,
        )
        return UserYaml.get_final_yaml(
            owner_yaml=repository.owner.yaml,
            repo_yaml=repository.yaml,
            commit_yaml=commit_yaml,
            owner_context=context,
        )


RegisteredUploadTask = celery_app.register_task(PreProcessUpload())
preprocess_upload_task = celery_app.tasks[RegisteredUploadTask.name]
