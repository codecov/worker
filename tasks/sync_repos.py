import logging
from datetime import datetime

from celery.exceptions import SoftTimeLimitExceeded
from shared.celery_config import sync_repos_task_name
from shared.torngit.exceptions import TorngitClientError
from sqlalchemy.dialects.postgresql import insert

from app import celery_app
from database.models import Owner, Repository
from helpers.environment import is_enterprise
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

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
        try:
            repos = await git.list_repos()
        except SoftTimeLimitExceeded:
            old_permissions = owner.permission or []
            log.warning(
                "System timed out while listing repos",
                extra=dict(
                    ownerid=owner.ownerid,
                    old_permissions=old_permissions[:100],
                    number_old_permissions=len(old_permissions),
                ),
            )
            raise
        except TorngitClientError as e:
            old_permissions = owner.permission or []
            log.warning(
                "Unable to verify user permissions on Github. Dropping all permissions",
                extra=dict(
                    ownerid=owner.ownerid,
                    old_permissions=old_permissions[:100],
                    number_old_permissions=len(old_permissions),
                ),
            )
            owner.permission = []
            return
        owners_by_id = {}

        count = 0
        for repo in repos:
            count += 1
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
            if count % 10 == 0:
                db_session.commit()

        log.info(
            "Updating permissions",
            extra=dict(ownerid=ownerid, username=username, repoids=private_project_ids),
        )
        old_permissions = owner.permission or []
        removed_permissions = set(old_permissions) - set(private_project_ids)
        if removed_permissions:
            log.warning(
                "Owner had permissions that are being removed",
                extra=dict(
                    old_permissions=old_permissions[:100],
                    number_old_permissions=len(old_permissions),
                    new_permissions=private_project_ids[:100],
                    number_new_permissions=len(private_project_ids),
                    removed_permissions=sorted(removed_permissions),
                    ownerid=ownerid,
                    username=owner.username,
                ),
            )

        # update user permissions
        owner.permission = sorted(set(private_project_ids))

    def upsert_owner(self, db_session, service, service_id, username):
        log.info(
            "Upserting owner",
            extra=dict(git_service=service, service_id=service_id, username=username),
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
        log.debug("Upserting repo", extra=dict(ownerid=ownerid, repo_data=repo_data))
        repo = (
            db_session.query(Repository)
            .filter(
                Repository.ownerid == ownerid,
                Repository.service_id == str(repo_data["service_id"]),
            )
            .first()
        )

        if repo:
            # Found the exact repo. Let's just update
            repo.private = repo_data["private"]
            repo.language = repo_data["language"]
            repo.name = repo_data["name"]
            repo.deleted = False
            repo.updatestamp = datetime.now()
            repo_id = repo.repoid
            return repo_id
        # repo was not found, could be a different owner
        repo_correct_serviceid_wrong_owner = (
            db_session.query(Repository)
            .join(Owner, Repository.ownerid == Owner.ownerid)
            .filter(
                Repository.service_id == str(repo_data["service_id"]),
                Owner.service == service,
            )
            .first()
        )
        # repo was not found, could be a different service_id
        repo_correct_owner_wrong_service_id = (
            db_session.query(Repository)
            .filter(
                Repository.ownerid == ownerid, Repository.name == repo_data["name"],
            )
            .first()
        )
        if (
            repo_correct_serviceid_wrong_owner is not None
            and repo_correct_owner_wrong_service_id is not None
        ):
            # But it cannot be both different owner and different service_id
            log.warning(
                "There is a repo with the right service_id and a repo with the right slug, but they are not the same",
                extra=dict(
                    repo_data=repo_data,
                    repo_correct_serviceid_wrong_owner=dict(
                        repoid=repo_correct_serviceid_wrong_owner.repoid,
                        slug=repo_correct_serviceid_wrong_owner.slug,
                        service_id=repo_correct_serviceid_wrong_owner.service_id,
                    ),
                    repo_correct_owner_wrong_service_id=dict(
                        repoid=repo_correct_owner_wrong_service_id.repoid,
                        slug=repo_correct_owner_wrong_service_id.slug,
                        service_id=repo_correct_owner_wrong_service_id.service_id,
                    ),
                ),
            )
            # We will have to assume the user has access to the service_id one, since
            # the service_id is the Github identity value
            return repo_correct_serviceid_wrong_owner.repoid

        if repo_correct_serviceid_wrong_owner:
            repo_id = repo_correct_serviceid_wrong_owner.repoid
            # repo exists, but wrong owner
            repo_wrong_owner = repo_correct_serviceid_wrong_owner
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
            db_session.flush()
            return repo_wrong_owner.repoid
        # could be correct owner but wrong service_id (repo deleted and recreated)
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
            repo_correct_owner_wrong_service_id.using_integration = using_integration
            repo_correct_owner_wrong_service_id.updatestamp = datetime.now()
            db_session.flush()
            return repo_correct_owner_wrong_service_id.repoid
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
        return new_repo.repoid


RegisteredSyncReposTask = celery_app.register_task(SyncReposTask())
sync_repos_task = celery_app.tasks[SyncReposTask.name]
