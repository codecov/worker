import logging
from typing import List, Optional

from asgiref.sync import async_to_sync
from shared.celery_config import sync_repo_languages_gql_task_name
from shared.torngit.exceptions import TorngitError, TorngitRateLimitError
from sqlalchemy import String
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.core import Owner, Repository
from helpers.clock import get_utc_now
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class SyncRepoLanguagesGQLTask(BaseCodecovTask, name=sync_repo_languages_gql_task_name):
    def run_impl(
        self,
        db_session: Session,
        org_username: String,
        current_owner_id=int,
        *args,
        **kwargs
    ):
        # Fetch current owner and org of interest from DB
        current_owner: Owner = (
            db_session.query(Owner).filter(Owner.ownerid == current_owner_id).first()
        )
        org: Owner = (
            db_session.query(Owner)
            .filter(Owner.username == org_username, Owner.service == "github")
            .first()
        )
        if current_owner is None or org is None:
            return {"successful": False, "error": "no_owner_in_db"}

        org_db_repositories: List[Repository] = (
            db_session.query(Repository).filter(Repository.ownerid == org.ownerid).all()
        )
        owner_service = get_owner_provider_service(owner=current_owner)

        try:
            repos_in_github: dict[str, List[str]] = async_to_sync(
                owner_service.get_repos_with_languages_graphql
            )(owner_username=org_username)
        except TorngitRateLimitError:
            log.warning(
                "Unable to fetch repositories due to rate limit error",
                extra=dict(current_owner_id=current_owner_id, org_id=org.ownerid),
            )
            return {"successful": False, "error": "torngit_rate_limit_error"}
        except TorngitError:
            log.warning(
                "There was an error in torngit",
                extra=dict(current_owner_id=current_owner_id, org_id=org.ownerid),
            )
            return {"successful": False, "error": "torngit_error"}

        print("helloo!", repos_in_github)

        updated_repoids = []
        for db_repo in org_db_repositories:
            repo_langs_from_github: Optional[List[str]] = repos_in_github.get(
                db_repo.name
            )
            if repo_langs_from_github is not None:
                updated_repoids.append(db_repo.repoid)
                db_repo.languages = repos_in_github[db_repo.name]
                db_repo.languages_last_updated = get_utc_now()
                db_session.flush()

        log.info(
            "Repo languages sync done",
            extra=dict(username=org_username, repoids=updated_repoids),
        )

        return {"successful": True}


RegisteredSyncRepoLanguagesGQLTask = celery_app.register_task(
    SyncRepoLanguagesGQLTask()
)
sync_repo_languages_gql_task = celery_app.tasks[RegisteredSyncRepoLanguagesGQLTask.name]
