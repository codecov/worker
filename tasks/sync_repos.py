import logging
from datetime import datetime

from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.celery_config import sync_repos_task_name
from shared.metrics import metrics
from shared.torngit.exceptions import TorngitClientError
from sqlalchemy import and_

from app import celery_app
from database.models import Owner, Repository
from rollouts import LIST_REPOS_GENERATOR_BY_OWNER_SLUG, owner_slug
from services.owner import get_owner_provider_service
from services.redis import get_redis_connection
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)
metrics_scope = "worker.SyncReposTask"


class SyncReposTask(BaseCodecovTask, name=sync_repos_task_name):
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

    ignore_result = False

    async def run_async(
        self,
        db_session,
        previous_results=None,
        *,
        ownerid,
        username=None,
        using_integration=False,
        **kwargs,
    ):
        log.info(
            "Sync repos",
            extra=dict(
                ownerid=ownerid, username=username, using_integration=using_integration
            ),
        )
        owner = db_session.query(Owner).filter(Owner.ownerid == ownerid).first()

        assert owner, "Owner not found"

        lock_name = f"syncrepos_lock_{ownerid}_{using_integration}"
        redis_connection = get_redis_connection()
        try:
            with redis_connection.lock(
                lock_name,
                timeout=max(300, self.hard_time_limit_task),
                blocking_timeout=5,
            ):
                git = get_owner_provider_service(owner, using_integration)
                if using_integration:
                    with metrics.timer(f"{metrics_scope}.sync_repos_using_integration"):
                        await self.sync_repos_using_integration(
                            db_session, git, owner, username
                        )
                else:
                    with metrics.timer(f"{metrics_scope}.sync_repos"):
                        await self.sync_repos(
                            db_session, git, owner, username, using_integration
                        )
        except LockError:
            log.warning("Unable to sync repos because another task is already doing it")

    async def sync_repos_using_integration(self, db_session, git, owner, username):
        ownerid = owner.ownerid
        log.info(
            "Syncing repos using integration",
            extra=dict(ownerid=ownerid, username=username),
        )

        total_missing_repos = []
        # We're testing processing repos a page at a time and this helper
        # function avoids duplicating the code in the old and new paths
        def process_repos(repos):
            service_ids = {repo["repo"]["service_id"] for repo in repos}
            if service_ids:
                # Querying through the `Repository` model is cleaner, but we
                # need to go through the table object instead if we want to
                # use a Postgres `RETURNING` clause like this.
                table = Repository.__table__
                update_statement = (
                    table.update()
                    .returning(table.columns.service_id)
                    .where(
                        and_(
                            table.columns.ownerid == ownerid,
                            table.columns.service_id.in_(service_ids),
                        )
                    )
                    .values(using_integration=True)
                )
                result = db_session.execute(update_statement)
                updated_service_ids = {r[0] for r in result.fetchall()}

                # The set of repos our app can see minus the set of repos we
                # just updated = the set of repos we need to insert.
                missing_service_ids = service_ids - updated_service_ids
                missing_repos = [
                    repo
                    for repo in repos
                    if repo["repo"]["service_id"] in missing_service_ids
                ]

                for repo in missing_repos:
                    repo_data = repo["repo"]
                    new_repo = Repository(
                        ownerid=ownerid,
                        service_id=repo_data["service_id"],
                        name=repo_data["name"],
                        language=repo_data["language"],
                        private=repo_data["private"],
                        branch=repo_data["branch"],
                        using_integration=True,
                    )
                    db_session.add(new_repo)
                db_session.flush()
                total_missing_repos.extend(missing_repos)

        # Here comes the actual function
        received_repos = False
        if LIST_REPOS_GENERATOR_BY_OWNER_SLUG.check_value(
            owner_slug(owner), default=False
        ):
            with metrics.timer(
                f"{metrics_scope}.sync_repos_using_integration.list_repos_generator"
            ):
                async for page in git.list_repos_using_installation_generator(username):
                    received_repos = True
                    process_repos(page)
        else:
            with metrics.timer(
                f"{metrics_scope}.sync_repos_using_integration.list_repos"
            ):
                repos = await git.list_repos_using_installation(username)
            if repos:
                received_repos = True
                process_repos(repos)

        # If the installation returned no repos, we were probably disabled and
        # should indicate as much on this owner's repositories.
        if not received_repos:
            db_session.query(Repository).filter(
                Repository.ownerid == ownerid, Repository.using_integration.is_(True)
            ).update({Repository.using_integration: False}, synchronize_session=False)

        log.info(
            "Repo sync using integration done",
            extra=dict(repoids=total_missing_repos),
        )

    async def sync_repos(self, db_session, git, owner, username, using_integration):
        service = owner.service
        ownerid = owner.ownerid
        private_project_ids = []

        log.info(
            "Syncing repos without integration",
            extra=dict(ownerid=ownerid, username=username, service=service),
        )

        repoids = []
        owners_by_id = {}
        # We're testing processing repos a page at a time and this helper
        # function avoids duplicating the code in the old and new paths
        def process_repos(repos):
            for repo in repos:
                # Time how long processing a single repo takes so we can estimate how
                # performance degrades. Sampling at 10% will be enough.
                with metrics.timer(f"{metrics_scope}.process_each_repo", rate=0.1):
                    _ownerid = owners_by_id.get(
                        (
                            service,
                            repo["owner"]["service_id"],
                            repo["owner"]["username"],
                        )
                    )
                    if not _ownerid:
                        _ownerid = self.upsert_owner(
                            db_session,
                            service,
                            repo["owner"]["service_id"],
                            repo["owner"]["username"],
                        )
                        owners_by_id[
                            (
                                service,
                                repo["owner"]["service_id"],
                                repo["owner"]["username"],
                            )
                        ] = _ownerid

                    repoid = self.upsert_repo(
                        db_session, service, _ownerid, repo["repo"], using_integration
                    )

                    repoids.append(repoid)

                    if repo["repo"].get("fork"):
                        _ownerid = self.upsert_owner(
                            db_session,
                            service,
                            repo["repo"]["fork"]["owner"]["service_id"],
                            repo["repo"]["fork"]["owner"]["username"],
                        )

                        _repoid = self.upsert_repo(
                            db_session, service, _ownerid, repo["repo"]["fork"]["repo"]
                        )

                        repoids.append(_repoid)

                        if repo["repo"]["fork"]["repo"]["private"]:
                            private_project_ids.append(int(_repoid))
                    if repo["repo"]["private"]:
                        private_project_ids.append(int(repoid))
                    db_session.commit()

        try:
            if LIST_REPOS_GENERATOR_BY_OWNER_SLUG.check_value(
                owner_slug(owner), default=False
            ):
                with metrics.timer(f"{metrics_scope}.sync_repos.list_repos_generator"):
                    async for page in git.list_repos_generator():
                        process_repos(page)
            else:
                # get my repos (and team repos)
                with metrics.timer(f"{metrics_scope}.sync_repos.list_repos"):
                    repos = await git.list_repos()
                    process_repos(repos)
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

        log.info("Repo sync done", extra=dict(repoids=repoids))

    def upsert_owner(self, db_session, service, service_id, username):
        log.info(
            "Upserting owner",
            extra=dict(git_service=service, service_id=service_id, username=username),
        )
        owner = (
            db_session.query(Owner)
            .filter(Owner.service == service, Owner.service_id == service_id)
            .first()
        )

        if owner:
            if (owner.username or "").lower() != username.lower():
                owner.username = username
        else:
            owner = Owner(service=service, service_id=service_id, username=username)
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
                Repository.service_id == repo_data["service_id"],
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
                Repository.service_id == repo_data["service_id"],
                Owner.service == service,
            )
            .first()
        )
        # repo was not found, could be a different service_id
        repo_correct_owner_wrong_service_id = (
            db_session.query(Repository)
            .filter(Repository.ownerid == ownerid, Repository.name == repo_data["name"])
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
                "Updating repo - wrong owner",
                extra=dict(
                    ownerid=ownerid,
                    repo_id=repo_wrong_owner.repoid,
                    repo_name=repo_data["name"],
                ),
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
                "Updating repo - correct owner, wrong service_id",
                extra=dict(
                    ownerid=ownerid,
                    repo_id=repo_correct_owner_wrong_service_id.service_id,
                    repo_name=repo_data["name"],
                ),
            )
            repo_correct_owner_wrong_service_id.service_id = repo_data["service_id"]
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
            service_id=repo_data["service_id"],
            name=repo_data["name"],
            language=repo_data["language"],
            private=repo_data["private"],
            branch=repo_data["branch"],
            using_integration=using_integration,
        )
        log.info(
            "Inserting repo",
            extra=dict(
                ownerid=ownerid, repo_id=new_repo.repoid, repo_name=new_repo.name
            ),
        )
        db_session.add(new_repo)
        db_session.flush()
        return new_repo.repoid


RegisteredSyncReposTask = celery_app.register_task(SyncReposTask())
sync_repos_task = celery_app.tasks[SyncReposTask.name]
