import logging

import shared.torngit as torngit
from asgiref.sync import async_to_sync
from sqlalchemy.orm.session import Session

from database.models.core import GithubAppInstallation, Repository

log = logging.getLogger(__name__)


# GH App Backfills
# Looping and adding all repositories in the installation app
def add_repos_service_ids_from_provider(
    db_session: Session,
    ownerid: int,
    owner_service: torngit.base.TorngitBaseAdapter,
    gh_app_installation: GithubAppInstallation,
):
    # TODO: Convert this to the generator function
    repos = async_to_sync(owner_service.list_repos_using_installation)()

    if repos:
        # Fetching all repos service ids we have for that owner in the DB
        repo_service_ids_in_db = [
            repo.service_id
            for repo in db_session.query(Repository.service_id)
            .filter_by(ownerid=ownerid)
            .all()
        ]

        # Add service ids from provider that we have DB records for to a list
        new_repo_service_ids = []
        for repo in repos:
            repo_data = repo["repo"]
            service_id = repo_data["service_id"]
            if service_id and service_id in repo_service_ids_in_db:
                new_repo_service_ids.append(service_id)
        log.info(
            "Added the following repo service ids to this gh app installation",
            extra=dict(
                ownerid=ownerid,
                installation_id=gh_app_installation.installation_id,
                new_repo_service_ids=new_repo_service_ids,
            ),
        )
        gh_app_installation.repository_service_ids = new_repo_service_ids
        db_session.commit()


# Check if gh selection is set to all and act accordingly
def maybe_set_installation_to_all_repos(
    db_session: Session,
    owner_service,
    gh_app_installation: GithubAppInstallation,
):
    remote_gh_app_installation = async_to_sync(owner_service.get_gh_app_installation)(
        installation_id=gh_app_installation.installation_id
    )
    repository_selection = remote_gh_app_installation.get("repository_selection", "")
    if repository_selection == "all":
        gh_app_installation.repository_service_ids = None
        db_session.commit()
        log.info(
            "Selection is set to all, no installation is needed",
            extra=dict(ownerid=gh_app_installation.ownerid),
        )
        return True
    return False
