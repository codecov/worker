import logging
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert

from app import celery_app
from celery_config import sync_repos_task_name
from shared.config import get_config
from helpers.environment import is_enterprise
from tasks.base import BaseCodecovTask
from database.models import Owner, Repository
from services.owner import get_owner_provider_service

log = logging.getLogger(__name__)


class SyncReposTask(BaseCodecovTask):
    """This task syncs the repos for a user in the same way as the legacy "refresh" task.

        High-level steps:

        1. Get repos for the user. This is all of the repos owned by the user and those
           in other teams/orgs/groups that the user has permission for. If using a GitHub
           integration, we get all the repos included in the integration.

        2. Loop over repos and upsert the owner, repo, and fork (if any) into the database.

        3. Update the permissions for the user (permissions col in the owners table).

        4. Set the bot for owners (teams/orgs/groups) that have private repos. This is so
           we have a link to a valid token through the bot user for calls to the provider
           service (GitHub, Gitlab, Bitbucket, ...).
    """

    name = sync_repos_task_name
    ignore_result = False

    async def run_async(
        self,
        db_session,
        previous_results=None,
        *,
        ownerid,
        username=None,
        using_integration=False,
        **kwargs
    ):
        log.info(
            "Sync repos",
            extra=dict(
                ownerid=ownerid, username=username, using_integration=using_integration
            ),
        )
        owner = db_session.query(Owner).filter(Owner.ownerid == ownerid).first()

        assert owner, "Owner not found"

        git = get_owner_provider_service(owner, using_integration)

        if using_integration:
            await self.sync_repos_using_integration(db_session, git, ownerid, username)
        else:
            await self.sync_repos(db_session, git, owner, username, using_integration)

    async def sync_repos_using_integration(self, db_session, git, ownerid, username):
        repo_service_ids = await git.list_repos_using_installation(username)
        if repo_service_ids:
            repo_service_ids = list(map(str, repo_service_ids))
            if repo_service_ids:
                db_session.query(Repository).filter(
                    Repository.ownerid == ownerid,
                    Repository.service_id.in_(repo_service_ids),
                    Repository.using_integration.isnot(True),
                ).update(
                    {Repository.using_integration: True}, synchronize_session=False
                )
        else:
            db_session.query(Repository).filter(
                Repository.ownerid == ownerid, Repository.using_integration.is_(True)
            ).update({Repository.using_integration: False}, synchronize_session=False)

    async def sync_repos(self, db_session, git, owner, username, using_integration):
        service = owner.service
        ownerid = owner.ownerid
        private_project_ids = []

        # get my repos (and team repos)
        repos = await git.list_repos()
        owners_by_id = {}

        for repo in repos:
            _ownerid = owners_by_id.get(
                (service, repo["owner"]["service_id"], repo["owner"]["username"])
            )
            if not _ownerid:
                _ownerid = self.upsert_owner(
                    db_session,
                    service,
                    repo["owner"]["service_id"],
                    repo["owner"]["username"],
                )
                owners_by_id[
                    (service, repo["owner"]["service_id"], repo["owner"]["username"])
                ] = _ownerid

            repoid = self.upsert_repo(
                db_session, service, _ownerid, repo["repo"], using_integration
            )

            if repo["repo"]["fork"]:
                _ownerid = self.upsert_owner(
                    db_session,
                    service,
                    repo["repo"]["fork"]["owner"]["service_id"],
                    repo["repo"]["fork"]["owner"]["username"],
                )

                _repoid = self.upsert_repo(
                    db_session, service, _ownerid, repo["repo"]["fork"]["repo"]
                )

                if repo["repo"]["fork"]["repo"]["private"]:
                    private_project_ids.append(int(_repoid))
            if repo["repo"]["private"]:
                private_project_ids.append(int(repoid))

        log.info(
            "Updating permissions",
            extra=dict(ownerid=ownerid, username=username, repoids=private_project_ids),
        )
        removed_permissions = set(owner.permission) - set(private_project_ids)
        if removed_permissions:
            log.warning(
                "Owner had permissions that are being removed",
                extra=dict(
                    old_permissions=owner.permission,
                    new_permissions=private_project_ids,
                    removed_permissions=sorted(removed_permissions),
                    ownerid=ownerid,
                    username=username,
                ),
            )

        # update user permissions
        owner.permission = sorted(set(private_project_ids))

    def upsert_owner(self, db_session, service, service_id, username):
        log.info(
            "Upserting owner",
            extra=dict(service=service, service_id=service_id, username=username),
        )
        owner = (
            db_session.query(Owner)
            .filter(Owner.service == service, Owner.service_id == str(service_id))
            .first()
        )

        if owner:
            if (owner.username or "").lower() != username.lower():
                owner.username = username
        else:
            owner = Owner(
                service=service, service_id=str(service_id), username=username
            )
            db_session.add(owner)
            db_session.flush()

        return owner.ownerid

    def upsert_repo(
        self, db_session, service, ownerid, repo_data, using_integration=None
    ):
        log.info("Upserting repo", extra=dict(ownerid=ownerid, repo_data=repo_data))
        repo = (
            db_session.query(Repository)
            .filter(
                Repository.ownerid == ownerid,
                Repository.service_id == str(repo_data["service_id"]),
            )
            .first()
        )

        if repo:
            repo.private = repo_data["private"]
            repo.language = repo_data["language"]
            repo.name = repo_data["name"]
            repo.deleted = False
            repo.updatestamp = datetime.now()
            repo_id = repo.repoid
        else:
            # repo was not found, could be a different owner
            repo_id = (
                db_session.query(Repository.repoid)
                .join(Owner, Repository.ownerid == Owner.ownerid)
                .filter(
                    Repository.service_id == str(repo_data["service_id"]),
                    Owner.service == service,
                )
                .first()
            )

            if repo_id:
                # repo exists, but wrong owner
                repo_wrong_owner = (
                    db_session.query(Repository)
                    .filter(Repository.repoid == repo_id)
                    .first()
                )

                if repo_wrong_owner:
                    log.info(
                        "Upserting repo - wrong owner",
                        extra=dict(ownerid=ownerid, repo_id=repo_wrong_owner.repoid),
                    )
                    repo_wrong_owner.ownerid = ownerid
                    repo_wrong_owner.private = repo_data["private"]
                    repo_wrong_owner.language = repo_data["language"]
                    repo_wrong_owner.name = repo_data["name"]
                    repo_wrong_owner.deleted = False
                    repo_wrong_owner.updatestamp = datetime.now()
                    repo_id = repo_wrong_owner.repoid
                else:
                    # the repository name exists, but wrong service_id
                    repo_wrong_service_id = (
                        db_session.query(Repository)
                        .filter(
                            Repository.ownerid == ownerid,
                            Repository.name == repo_data["name"],
                        )
                        .first()
                    )

                    if repo_wrong_service_id:
                        log.info(
                            "Upserting repo - wrong service_id",
                            extra=dict(
                                ownerid=ownerid,
                                repo_id=repo_wrong_service_id.service_id,
                            ),
                        )
                        repo_wrong_service_id.service_id = repo_data["service_id"]
                        repo_wrong_service_id.private = repo_data["private"]
                        repo_id = repo_wrong_owner.repoid
            else:
                # could be correct owner but wrong service_id (repo deleted and recreated)
                repo_correct_owner_wrong_service_id = (
                    db_session.query(Repository)
                    .filter(
                        Repository.ownerid == ownerid,
                        Repository.name == repo_data["name"],
                    )
                    .first()
                )

                if repo_correct_owner_wrong_service_id:
                    log.info(
                        "Upserting repo - correct owner, wrong service_id",
                        extra=dict(
                            ownerid=ownerid,
                            repo_id=repo_correct_owner_wrong_service_id.service_id,
                        ),
                    )
                    repo_correct_owner_wrong_service_id.service_id = str(
                        repo_data["service_id"]
                    )
                    repo_correct_owner_wrong_service_id.name = repo_data["name"]
                    repo_correct_owner_wrong_service_id.language = repo_data["language"]
                    repo_correct_owner_wrong_service_id.private = repo_data["private"]
                    repo_correct_owner_wrong_service_id.using_integration = (
                        using_integration
                    )
                    repo_correct_owner_wrong_service_id.updatestamp = datetime.now()
                    repo_id = repo_correct_owner_wrong_service_id.repoid
                else:
                    # repo does not exist, create it
                    new_repo = Repository(
                        ownerid=ownerid,
                        service_id=str(repo_data["service_id"]),
                        name=repo_data["name"],
                        language=repo_data["language"],
                        private=repo_data["private"],
                        branch=repo_data["branch"],
                        using_integration=using_integration,
                    )
                    db_session.add(new_repo)
                    db_session.flush()

                    repo_id = new_repo.repoid

        return repo_id


RegisteredSyncReposTask = celery_app.register_task(SyncReposTask())
sync_repos_task = celery_app.tasks[SyncReposTask.name]
