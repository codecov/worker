import logging
from datetime import datetime
from typing import List, Optional, Tuple

from asgiref.sync import async_to_sync
from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import LockError
from shared.celery_config import (sync_repo_languages_gql_task_name,
                                  sync_repo_languages_task_name,
                                  sync_repos_task_name)
from shared.config import get_config
from shared.helpers.redis import get_redis_connection
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import (TorngitClientError,
                                       TorngitServerFailureError)
from sqlalchemy import and_
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models import Owner, Repository
from services.owner import get_owner_provider_service
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
        db_session: Session,
        # `previous_results`` is added by celery if the task is chained.
        # It contains the results of tasks that came before this one in the chain
        previous_results=None,
        *,
        ownerid: int,
        username: Optional[str] = None,
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
                ownerid=ownerid,
                username=username,
                using_integration=using_integration,
                manual_trigger=manual_trigger,
                repository_service_ids=repository_service_ids,
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
                    ignore_installation=(not using_integration),
                )
                sync_repos_output = {}
                if using_integration:
                    sync_repos_output = async_to_sync(
                        self.sync_repos_using_integration
                    )(
                        db_session,
                        git,
                        owner,
                        username,
                        repository_service_ids=repository_service_ids,
                    )
                else:
                    sync_repos_output = async_to_sync(self.sync_repos)(
                        db_session, git, owner, username, using_integration
                    )

                if get_config(
                    "setup", "tasks", "sync_repo_languages", "enabled", default=True
                ):
                    self.sync_repos_languages(
                        sync_repos_output=sync_repos_output,
                        manual_trigger=manual_trigger,
                        current_owner=owner,
                    )
        except LockError:
            log.warning("Unable to sync repos because another task is already doing it")

    async def sync_repos_affected_repos_known(
        self,
        db_session: Session,
        git: TorngitBaseAdapter,
        owner: Owner,
        repository_service_ids: List[Tuple[int, str]] | None,
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

        log.info(
            "Sync missing repos if any",
            extra=dict(
                ownerid=owner.ownerid,
                missing_repo_service_ids=missing_repo_service_ids,
                num_missing_repos=len(missing_repo_service_ids),
                existing_repos=existing_repos,
                repository_service_ids=repository_service_ids,
            ),
        )

        # Get info from provider on the repos we don't have
        repos_to_search = [
            x[1]
            for x in repository_service_ids
            if str(x[0]) in missing_repo_service_ids
        ]
        async for repo_data in git.get_repos_from_nodeids_generator(
            repos_to_search, owner.username
        ):
            # Get or create owner
            if repo_data["owner"]["is_expected_owner"]:
                new_repo_ownerid = owner.ownerid
            else:
                upserted_owner_id = self.upsert_owner(
                    db_session,
                    git.service,
                    repo_data["owner"]["service_id"],
                    repo_data["owner"]["username"],
                )
                new_repo_ownerid = upserted_owner_id
            # Get or create repo
            # Yes we had issues trying to insert a repeated repo at this point.
            # Maybe race condition?
            repoid = self.upsert_repo(
                db_session=db_session,
                service=git.service,
                ownerid=new_repo_ownerid,
                repo_data={**repo_data, "service_id": str(repo_data["service_id"])},
                using_integration=True,
            )
            repoids_added.append(repoid)
        return repoids_added

    def _possibly_update_ghinstallation_covered_repos(
        self,
        git: TorngitBaseAdapter,
        owner: Owner,
        service_ids_listed: List[str],
    ):
        installation_used = git.data.get("installation")
        if installation_used is None:
            log.warning(
                "Failed to update ghapp covered repos. We don't know which installation is being used"
            )
        if (
            owner.github_app_installations is None
            or owner.github_app_installations == []
        ):
            log.warning(
                "Failed to possibly update ghapp covered repos. Owner has no installations",
            )
            return
        ghapp = next(
            filter(
                lambda obj: (
                    obj.installation_id == installation_used.get("installation_id")
                    and obj.app_id == installation_used.get("app_id")
                ),
                owner.github_app_installations,
            ),
            None,
        )
        if ghapp and ghapp.repository_service_ids is not None:
            covered_repos = set(ghapp.repository_service_ids)
            service_ids_listed_set = set(service_ids_listed)
            log.info(
                "Updating list of repos covered",
                extra=dict(
                    owner=owner.ownerid,
                    installation=ghapp.installation_id,
                    ghapp_id=ghapp.id,
                    added_repos_service_ids=covered_repos.difference(
                        service_ids_listed_set
                    ),
                ),
            )
            ghapp.repository_service_ids = list(covered_repos | service_ids_listed_set)

    async def sync_repos_using_integration(
        self,
        db_session: Session,
        git: TorngitBaseAdapter,
        owner: Owner,
        username: str,
        repository_service_ids: Optional[List[Tuple[int, str]]] = None,
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
            self._possibly_update_ghinstallation_covered_repos(git, owner, service_ids)
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
        # Below logic may not be needed if repository_service_ids exist, but
        # we have run into issues related to the sync task when repos are known
        # So we should still run it just in case and possibly update GithubInstallation.repository_service_ids
        # Instead of relying exclusively on the webhooks to do that
        # TODO: Maybe we don't need to run this every time, but once in a while just in case...
        async for page in git.list_repos_using_installation_generator(username):
            if page:
                received_repos = True
                process_repos(page)

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

        return {
            "service": git.service,
            "org_usernames": [owner.username],
            "repoids": repoids,
        }

    async def sync_repos(
        self,
        db_session: Session,
        git,
        owner: Owner,
        username: Optional[str],
        using_integration: bool,
    ):
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
            async for page in git.list_repos_generator():
                process_repos(page)

        except (
            SoftTimeLimitExceeded,
            TorngitClientError,
            TorngitServerFailureError,
        ) as e:
            old_permissions = owner.permission or []
            if isinstance(e, SoftTimeLimitExceeded):
                error_string = "System timed out while listing repos"
            else:
                error_string = "Torngit failure while listing repos"

            log.error(
                f"{error_string}. Permissions list may be incomplete",
                exc_info=True,
                extra=dict(
                    ownerid=owner.ownerid,
                    number_old_permissions=len(old_permissions),
                    number_new_permissions=len(set(private_project_ids)),
                ),
            )

        log.info(
            "Updating permissions",
            extra=dict(
                ownerid=ownerid, username=username, privaterepoids=private_project_ids
            ),
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

        log.info(
            "Repo sync done",
            extra=dict(ownerid=ownerid, username=username, repoids=repoids),
        )

        return {
            "service": git.service,
            "org_usernames": [item[2] for item in owners_by_id.keys()],
            "repoids": repoids,
        }

    def upsert_owner(
        self, db_session: Session, service: str, service_id: int, username: str
    ):
        log.info(
            "Upserting owner",
            extra=dict(git_service=service, service_id=service_id, username=username),
        )
        print("trigger overwatch")
        
        owner = (
            db_session.query(Owner)
            .filter(Owner.service == service, Owner.service_id == service_id)
            .first()
        )

        if owner:
            if (owner.username or "").lower() != username.lower():
                owner.username = username
        else:
            owner = Owner(
                service=service,
                service_id=service_id,
                username=username,
                createstamp=datetime.now(),
            )
            db_session.add(owner)
            db_session.flush()

        return owner.ownerid

    def upsert_repo(
        self,
        db_session: Session,
        service: str,
        ownerid: int,
        repo_data,
        using_integration: Optional[bool] = None,
    ):
        log.info(
            "Upserting repo",
            extra=dict(ownerid=ownerid, repo_data=repo_data),
        )
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
            has_changes = False
            if repo.private != repo_data["private"]:
                repo.private = repo_data["private"]
                has_changes = True
            if repo.language != repo_data["language"]:
                repo.language = repo_data["language"]
                has_changes = True
            if repo.name != repo_data["name"]:
                repo.name = repo_data["name"]
                has_changes = True
            if repo.deleted is not False:
                repo.deleted = False
                has_changes = True
            if has_changes:
                repo.updatestamp = datetime.now()
            repo_id = repo.repoid
            return repo_id
        # repo was not found, could be a different owner
        repo_correct_serviceid_wrong_owner = (
            db_session.query(Repository)
            .join(Owner, Repository.ownerid == Owner.ownerid)
            .filter(
                Repository.deleted == False,
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

    def sync_repos_languages(
        self, sync_repos_output: dict, manual_trigger: bool, current_owner: Owner
    ):
        log.info(
            "Syncing repos languages",
            extra=dict(
                ownerid=current_owner.ownerid,
                sync_repos_output=sync_repos_output,
                manual_trigger=manual_trigger,
            ),
        )
        if sync_repos_output:
            if sync_repos_output["service"] == "github":
                for owner_username in sync_repos_output["org_usernames"]:
                    self.app.tasks[sync_repo_languages_gql_task_name].apply_async(
                        kwargs=dict(
                            org_username=owner_username,
                            current_owner_id=current_owner.ownerid,
                        )
                    )
            else:
                for repoid in sync_repos_output["repoids"]:
                    self.app.tasks[sync_repo_languages_task_name].apply_async(
                        kwargs=dict(repoid=repoid, manual_trigger=manual_trigger)
                    )


RegisteredSyncReposTask = celery_app.register_task(SyncReposTask())
sync_repos_task = celery_app.tasks[SyncReposTask.name]
