import logging
from datetime import datetime
from typing import List, Optional, Tuple

from asgiref.sync import async_to_sync
from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.celery_config import sync_repo_languages_task_name, sync_repos_task_name
from shared.metrics import metrics
from shared.torngit.exceptions import TorngitClientError
from sqlalchemy import and_

from app import celery_app
from database.models import Owner, Repository
from rollouts import LIST_REPOS_GENERATOR_BY_OWNER_ID
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

    5. Fire off a task to sync every repository's available languages with its provider
       after finishing the sync.

    # About the `using_integration` argument
    `using_integration` is specific to GitHub users. When `using_integration==True` then this refresh
    task came from receiving some INSTALLATION event from GitHub indicating that the app installation
    for the user suffered some change.

    In this case we use the installation token to list repos from github, as opposed to the owner's token
    (there's possibly a difference in what repos the owner can see and what repos the app installation can see)
    """

    ignore_result = False

    def run_impl(
        self,
        db_session,
        # `previous_results`` is added by celery if the task is chained.
        # It contains the results of tasks that came before this one in the chain
        previous_results=None,
        *,
        ownerid,
        username=None,
        using_integration=False,
        manual_trigger=False,
        # `repository_service_ids` is optionally passed to the task
        # when using_integration=True so we know what are the repos affected.
        # Speeds up getting info from the git provider, but not required
        # objects are (service_id, node_id)
        repository_service_ids: Optional[List[Tuple[str, str]]] = None,
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
                git = get_owner_provider_service(
                    owner,
                    using_integration,
                    ignore_installation=(not using_integration),
                )
                synced_repoids = []
                if using_integration:
                    with metrics.timer(f"{metrics_scope}.sync_repos_using_integration"):
                        synced_repoids = async_to_sync(
                            self.sync_repos_using_integration
                        )(
                            db_session,
                            git,
                            owner,
                            username,
                            repository_service_ids=repository_service_ids,
                        )
                else:
                    with metrics.timer(f"{metrics_scope}.sync_repos"):
                        synced_repoids = async_to_sync(self.sync_repos)(
                            db_session, git, owner, username, using_integration
                        )

                self.sync_repos_languages(
                    synced_repoids=synced_repoids or [],
                    manual_trigger=manual_trigger,
                )
        except LockError:
            log.warning("Unable to sync repos because another task is already doing it")

    async def sync_repos_affected_repos_known(
        self,
        db_session,
        git,
        owner: Owner,
        repository_service_ids: Optional[List[Tuple[str, str]]],
    ):
        repoids_added = []
        # Casting to str in case celery interprets the service ID as a integer for some reason
        # As that has caused issues with testing locally
        service_ids = set(str(x[0]) for x in repository_service_ids)
        # Check what repos we already have in the DB
        existing_repos = set(
            map(
                lambda row_result: row_result[0],
                db_session.query(Repository.service_id)
                .filter(Repository.service_id.in_(service_ids))
                .all(),
            )
        )
        missing_repo_service_ids = service_ids.difference(existing_repos)

        # Get info from provider on the repos we don't have
        repos_to_search = [
            x[1] for x in repository_service_ids if x[0] in missing_repo_service_ids
        ]
        for repo_data in git.get_repos_from_nodeids_generator(
            repos_to_search, owner.username
        ):
            # Insert those repos
            new_repo = Repository(
                service_id=repo_data["service_id"],
                name=repo_data["name"],
                language=repo_data["language"],
                private=repo_data["private"],
                branch=repo_data["branch"],
                using_integration=True,
            )
            if repo_data["owner"]["is_expected_owner"]:
                new_repo.ownerid = owner.ownerid
            else:
                upserted_owner_id = self.upsert_owner(
                    db_session,
                    git.service,
                    repo_data["owner"]["service_id"],
                    repo_data["owner"]["username"],
                )
                new_repo.ownerid = upserted_owner_id
            db_session.add(new_repo)
            db_session.flush()
            repoids_added.append(new_repo.repoid)
        return repoids_added

    async def sync_repos_using_integration(
        self,
        db_session,
        git,
        owner,
        username,
        repository_service_ids: Optional[List[Tuple[str, str]]] = None,
    ):
        ownerid = owner.ownerid
        log.info(
            "Syncing repos using integration",
            extra=dict(ownerid=ownerid, username=username),
        )

        repoids = []
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
                    repoids.append(new_repo.repoid)

        # Here comes the actual function
        received_repos = False
        if repository_service_ids:
            # This flow is different from the ones below because the API already informed us the repos affected
            # So we can update those values directly
            repoids_added = await self.sync_repos_affected_repos_known(
                db_session, git, owner, repository_service_ids
            )
            repoids = repoids_added
        elif LIST_REPOS_GENERATOR_BY_OWNER_ID.check_value(
            owner_id=ownerid, default=False
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
            extra=dict(repoids_created=repoids, repoids_created_count=len(repoids)),
        )

        return repoids

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
            # if LIST_REPOS_GENERATOR_BY_OWNER_ID.check_value(
            #     owner_id=ownerid, default=False
            # ):
            #     with metrics.timer(f"{metrics_scope}.sync_repos.list_repos_generator"):
            #         async for page in git.list_repos_generator():
            #             process_repos(page)
            # else:
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

        return repoids

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

    def sync_repos_languages(self, synced_repoids: List[int], manual_trigger: bool):
        for repoid in synced_repoids:
            self.app.tasks[sync_repo_languages_task_name].apply_async(
                kwargs=dict(repoid=repoid, manual_trigger=manual_trigger)
            )


RegisteredSyncReposTask = celery_app.register_task(SyncReposTask())
sync_repos_task = celery_app.tasks[SyncReposTask.name]
