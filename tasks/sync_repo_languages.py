import logging

from sqlalchemy import String

from shared.celery_config import sync_repo_languages_task_name
from shared.torngit.exceptions import TorngitError
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.core import Repository
from helpers.clock import get_utc_now
from services.repository import get_repo_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

BUNDLE_ANALYSIS_LANGUAGES = ["javascript", "typescript"]

# We sync on repos that don't have the desired BA languages every 7 days
# TODO: make this number also tweakable by infra
REPOSITORY_LANGUAGE_SYNC_THRESHOLD = 7

class SyncRepoLanguagesTask(BaseCodecovTask, name=sync_repo_languages_task_name):
    async def run_async(
        self, db_session: Session, repoid: String, manual_trigger: bool = False, *args, **kwargs
    ):
        repository = db_session.query(Repository).get(repoid)
        now = get_utc_now()
        days_since_sync = REPOSITORY_LANGUAGE_SYNC_THRESHOLD
        if repository.languages_last_updated:
            print("should have not entered here")
            days_since_sync = abs((now - repository.languages_last_updated).days)

        desired_languages_intersection = set(BUNDLE_ANALYSIS_LANGUAGES).intersection(
            repository.languages
        )
        should_sync_languages = (
            days_since_sync >= REPOSITORY_LANGUAGE_SYNC_THRESHOLD
            and len(desired_languages_intersection) == 0
        ) or manual_trigger
        try:
            if should_sync_languages:
                print("should start syncing now!")
                log_extra = dict(
                    owner_id=repository.ownerid,
                    repository_id=repository.repoid,
                )
                log.info("Syncing repository languages", extra=log_extra)
                repository_service = get_repo_provider_service(repository)
                
                if repository.owner.service == "bitbucket" or repository.owner.service == "bitbucket_server":
                    languages = await repository_service.get_repo_languages(token=None, language=repository.language)
                else:
                    languages = await repository_service.get_repo_languages()
                repository.languages = languages
                repository.languages_last_updated = now
                db_session.flush()
                return {"successful": True}
        except TorngitError:
            log.warning(
                "Unable to find languages for this repository",
                dict(repository_id=repository.repoid),
            )
            return {"successful": False, "error": "no_repo"}

RegisteredSyncRepoLanguagesTask = celery_app.register_task(SyncRepoLanguagesTask())
sync_repo_language_task = celery_app.tasks[RegisteredSyncRepoLanguagesTask.name]
