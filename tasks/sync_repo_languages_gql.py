import logging
from services.owner import get_owner_provider_service
from shared.celery_config import sync_repo_languages_gql_task_name
from shared.torngit.exceptions import TorngitError
from sqlalchemy import String
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.core import Owner, Repository
from helpers.clock import get_utc_now
from helpers.exceptions import RepositoryWithoutValidBotError
from services.repository import get_repo_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

BUNDLE_ANALYSIS_LANGUAGES = ["javascript", "typescript"]

# We sync on repos that don't have the desired BA languages every 7 days
REPOSITORY_LANGUAGE_SYNC_THRESHOLD = 7


class SyncRepoLanguagesGQLTask(BaseCodecovTask, name=sync_repo_languages_gql_task_name):
    async def run_async(
        self, db_session: Session, org_username: String, manual_trigger=False, current_owner_id=int, *args, **kwargs
    ):
        # Fetch current owner and org you want to get repos of
        current_owner = db_session.query(Owner).filter(Owner.ownerid == current_owner_id).first()
        org = db_session.query(Owner).filter(Owner.username == org_username, Owner.service == "github").first()
        if current_owner is None or org is None:
            return {"successful": False, "error": "no_owner_in_db"}

        owner_service = get_owner_provider_service(
            owner=current_owner
        )

        repositories  = await owner_service.get_languages_graphql(
            org_username=org_username
        )

        # call gql endpoint and get all the repos
        # loop through each repo and make sure we have that repo in our DB
        #   db session call by ownerid (from line 1) + repo_name (from db response)
        #   check if you should_sync_languages)
        #   if so, update repository.languages = languages and repository.languages_last_updated = now


        # repository = db_session.query(Repository).get(repoid)
        # if repository is None:
        #     return {"successful": False, "error": "no_repo_in_db"}

        # now = get_utc_now()
        # days_since_sync = REPOSITORY_LANGUAGE_SYNC_THRESHOLD

        # if repository.languages_last_updated:
        #     days_since_sync = abs(
        #         (now.replace(tzinfo=None) - repository.languages_last_updated).days
        #     )

        # desired_languages_intersection = set(BUNDLE_ANALYSIS_LANGUAGES).intersection(
        #     repository.languages or {}
        # )

        # should_sync_languages = (
        #     days_since_sync >= REPOSITORY_LANGUAGE_SYNC_THRESHOLD
        #     and len(desired_languages_intersection) == 0
        # ) or manual_trigger

        # try:
        #     if should_sync_languages:
        #         log_extra = dict(
        #             owner_id=repository.ownerid or "",
        #             repository_id=repository.repoid,
        #         )
        #         log.info("Syncing repository languages", extra=log_extra)
        #         repository_service = get_repo_provider_service(repository)
        #         is_bitbucket_call = (
        #             repository.owner.service == "bitbucket"
        #             or repository.owner.service == "bitbucket_server"
        #         )
        #         if is_bitbucket_call:
        #             languages = await repository_service.get_repo_languages(
        #                 token=None, language=repository.language
        #             )
        #         else:
        #             languages = await repository_service.get_repo_languages()
        #         repository.languages = languages
        #         repository.languages_last_updated = now
        #         db_session.flush()
        #         return {"successful": True}
        # except TorngitError:
        #     log.warning(
        #         "Unable to find languages for this repository",
        #         extra=dict(repoid=repoid),
        #     )
        #     return {"successful": False, "error": "no_repo_in_provider"}
        # except RepositoryWithoutValidBotError:
        #     log.warning(
        #         "No valid bot found for repo",
        #         extra=dict(repoid=repoid),
        #     )
        #     return {"successful": False, "error": "no_bot"}


RegisteredSyncRepoLanguagesGQLTask = celery_app.register_task(SyncRepoLanguagesGQLTask())
sync_repo_languages_gql_task = celery_app.tasks[RegisteredSyncRepoLanguagesGQLTask.name]
