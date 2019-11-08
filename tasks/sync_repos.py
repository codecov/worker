import logging
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert

from app import celery_app
from celery_config import sync_repos_task_name
from helpers.config import get_config
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

    def write_to_db(self):
        return True

    async def run_async(self, db_session, ownerid, *, username=None, using_integration=False, **kwargs):
        log.info(
            'Sync repos',
            extra=dict(ownerid=ownerid, username=username, using_integration=using_integration)
        )
        owner = db_session.query(Owner).filter(
            Owner.ownerid == ownerid
        ).first()

        assert owner, 'Owner not found'
        service = owner.service

        git = get_owner_provider_service(owner, using_integration)

        if using_integration:
            repo_service_ids = await git.list_repos_using_installation(username)
            if repo_service_ids:
                repo_service_ids = tuple(map(str, repo_service_ids))
                if repo_service_ids:
                    db_session.query(Repository).filter(
                        Repository.ownerid == ownerid,
                        Repository.service_id.in_(repo_service_ids),
                        Repository.using_integration.isnot_(True)
                    ).update({
                        Repository.using_integration: True
                    }, synchronize_session=False)

                    db_session.query(Repository).filter(
                        Repository.ownerid == ownerid,
                        Repository.service_id.in_(repo_service_ids),
                        Repository.using_integration.is_(True)
                    ).update({
                        Repository.using_integration: False
                    }, synchronize_session=False)
            else:
                db_session.query(Repository).filter(
                    Repository.ownerid == ownerid,
                    Repository.using_integration.is_(True)
                ).update({
                    Repository.using_integration: False
                }, synchronize_session=False)
        else:
            private_project_ids = []

            # get my repos (and team repos)
            repos = await git.list_repos()
            owners_by_id = {}

            for repo in repos:
                _ownerid = owners_by_id.get((
                    service,
                    repo['owner']['service_id'],
                    repo['owner']['username']
                ))
                if not _ownerid:
                    _ownerid = self.upsert_owner(
                        db_session,
                        service,
                        repo['owner']['service_id'],
                        repo['owner']['username']
                    )
                    owners_by_id[(
                        service,
                        repo['owner']['service_id'],
                        repo['owner']['username']
                    )] = _ownerid

                repoid = self.upsert_repo(
                    db_session,
                    service,
                    _ownerid,
                    repo['repo'],
                    using_integration
                )

                if repo['repo']['fork']:
                    _ownerid = self.upsert_owner(
                        db_session,
                        service,
                        repo['repo']['fork']['owner']['service_id'],
                        repo['repo']['fork']['owner']['username']
                    )

                    _repoid = self.upsert_repo(
                        db_session,
                        service,
                        _ownerid,
                        repo['repo']['fork']['repo']
                    )

                    if repo['repo']['fork']['repo']['private']:
                        private_project_ids.append(str(_repoid))
                if repo['repo']['private']:
                    private_project_ids.append(str(repoid))

            log.info(
                'updating permissions',
                extra=dict(ownerid=ownerid, username=username, repoids=private_project_ids)
            )

            # update user permissions
            owner.permission = sorted(map(int, list(set(owner.permission + private_project_ids))))

            #  choose a bot
            if private_project_ids:
                owner_ids_to_set = list(map(str, owners_by_id.values()))
                self.set_bot(db_session, ownerid, service, owner_ids_to_set)


    def upsert_owner(self, db_session, service, service_id, username):
        log.info(
            'upserting owner',
            extra=dict(service=service, service_id=service_id, username=username)
        )
        owner = db_session.query(Owner).filter(
            Owner.service == service,
            Owner.service_id == str(service_id)
        ).first()

        if owner:
            if (owner.username or '').lower() != username.lower():
                owner.username = username
        else:
            owner = Owner(
                service=service,
                service_id=str(service_id),
                username=username
            )
            db_session.add(owner)
            db_session.flush()
            
        return owner.ownerid


    def upsert_repo(self, db_session, service, ownerid, repo_data, using_integration=None):
        log.info(
            'upserting repo',
            extra=dict(ownerid=ownerid, repo_data=repo_data)
        )
        repo = db_session.query(Repository).filter(
            Repository.ownerid == ownerid,
            Repository.service_id == str(repo_data['service_id'])
        ).first()

        if repo:
            repo.private = repo_data['private']
            repo.language = repo_data['language']
            repo.name = repo_data['name']
            repo.deleted = False
            repo.updatestamp = datetime.now()
            repo_id = repo.repoid
        else:
            # repo was not found, could be a different owner
            repo_id = db_session.query(Repository.repoid).join(
                Owner, Repository.ownerid == Owner.ownerid
            ).filter(
                Repository.service_id == str(repo_data['service_id']),
                Owner.service == service
            ).first()

            if repo_id:
                try:
                    # repo exists, but wrong owner
                    repo_wrong_owner = db_session.query(Repository).filter(
                        Repository.repoid == repo_id
                    ).first()

                    if repo_wrong_owner:
                        repo_wrong_owner.ownerid = ownerid
                        repo_wrong_owner.private = repo_data['private']
                        repo_wrong_owner.language = repo_data['language']
                        repo_wrong_owner.name = repo_data['name']
                        repo_wrong_owner.deleted = False
                        repo_wrong_owner.updatestamp = datetime.now()
                        repo_id = repo_wrong_owner.repoid
                except:
                    # the repository name exists, but wrong service_id
                    repo_wrong_service_id = db_session.query(Repository).filter(
                        Repository.ownerid == ownerid,
                        Repository.name == repo_data['name']
                    ).first()

                    if repo_wrong_service_id:
                        repo_wrong_service_id.service_id = repo_data['service_id']
                        repo_wrong_service_id.private = repo_data['private']
                        repo_id = repo_wrong_owner.repoid
            else:
                # repo does not exist, create it
                insert_data = dict(
                    ownerid=ownerid,
                    service_id=str(repo_data['service_id']),
                    name=repo_data['name'],
                    language=repo_data['language'],
                    private=repo_data['private'],
                    branch=repo_data['branch'],
                    using_integration=using_integration
                )

                conflict_data = dict(
                    service_id=str(repo_data['service_id']),
                    name=repo_data['name'],
                    language=repo_data['language'],
                    private=repo_data['private'],
                    using_integration=using_integration,
                    updatestamp=datetime.now()
                )

                i = insert(Repository) \
                        .values(insert_data) \
                        .on_conflict_do_update(constraint='repos_slug', set_=conflict_data) \
                        .returning(Repository.repoid)

                [(new_repoid,)] = db_session.execute(i).fetchall()
                repo_id = new_repoid

        return repo_id


    def set_bot(self, db_session, ownerid, service, owner_ids):
        # remove myself
        if str(ownerid) in owner_ids:
            owner_ids.remove(str(ownerid))

        if owner_ids and (
            not self.enterprise or                # is production
            get_config((service, 'bot')) is None  # or no bot is set in yaml
        ):
            # we can see private repos, make me the bot
            db_session.query(Owner).filter(
                Owner.service == service,
                Owner.ownerid.in_(tuple(owner_ids)),
                Owner.bot_id.is_(None),
                Owner.oauth_token.is_(None)
            ).update({
                Owner.bot_id: ownerid
            }, synchronize_session=False)


RegisteredSyncReposTask = celery_app.register_task(SyncReposTask())
sync_repos_task = celery_app.tasks[SyncReposTask.name]
