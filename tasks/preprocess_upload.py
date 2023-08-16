import logging

from redis.exceptions import LockError
from shared.torngit.exceptions import TorngitClientError
from shared.validation.exceptions import InvalidYamlException
from shared.yaml import UserYaml

from app import celery_app
from database.enums import CommitErrorTypes
from database.models import Commit
from helpers.save_commit_error import save_commit_error
from services.redis import get_redis_connection
from services.report import ReportService
from services.repository import get_repo_provider_service
from services.yaml import save_repo_yaml_to_database_if_needed
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class PreProcessUpload(BaseCodecovTask):

    """
    The main goal for this task is to carry forward flags from previous uploads
    and save the new carried-forawrded upload in the db,as a pre-step for
    uploading a report to codecov
    """

    name = "app.tasks.upload.PreProcessUpload"

    async def run_async(
        self,
        db_session,
        *,
        repoid: int,
        commitid: str,
        report_code: str,
        **kwargs,
    ):
        log.info(
            "Received preprocess upload task",
            extra=dict(repoid=repoid, commit=commitid, report_code=report_code),
        )
        lock_name = f"preprocess_upload_lock_{repoid}_{commitid}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(
                lock_name,
                timeout=60 * 5,
                blocking_timeout=5,
            ):
                return await self.process_async_within_lock(
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
            return {"preprocessed_upload": False}

    async def process_async_within_lock(
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
        repository = commit.repository
        repository_service = get_repo_provider_service(repository, commit)
        if repository_service:
            commit_yaml = await self.fetch_commit_yaml_and_possibly_store(
                commit, repository_service
            )
        else:
            commit_yaml = UserYaml.get_final_yaml(
                owner_yaml=repository.owner.yaml,
                repo_yaml=repository.yaml,
                commit_yaml=None,
                ownerid=repository.owner.ownerid,
            )
        report_service = ReportService(commit_yaml)
        commit_report = await report_service.initialize_and_save_report(
            commit, report_code
        )
        return {"preprocessed_upload": True, "reportid": str(commit_report.external_id)}

    async def fetch_commit_yaml_and_possibly_store(self, commit, repository_service):
        repository = commit.repository
        try:
            log.info(
                "Fetching commit yaml from provider for commit",
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
            commit_yaml = await fetch_commit_yaml_from_provider(
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
        return UserYaml.get_final_yaml(
            owner_yaml=repository.owner.yaml,
            repo_yaml=repository.yaml,
            commit_yaml=commit_yaml,
            ownerid=repository.owner.ownerid,
        )


RegisteredUploadTask = celery_app.register_task(PreProcessUpload())
preprocess_upload_task = celery_app.tasks[RegisteredUploadTask.name]
