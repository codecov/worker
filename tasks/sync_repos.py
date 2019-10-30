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
    """This task syncs the repos for a user
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
                    # self.db.query("""UPDATE repos
                    #                     set using_integration = true
                    #                     where ownerid=%s
                    #                     and service_id in %s
                    #                     and using_integration is not true;""",
                    #                 ownerid, repo_service_ids)
                    db_session.query(Repository).filter(
                        Repository.ownerid == ownerid,
                        Repository.service_id.in_(repo_service_ids),
                        Repository.using_integration.isnot_(True)
                    ).update({
                        Repository.using_integration: True
                    }, synchronize_session=False)

                    # self.db.query("""UPDATE repos
                    #                     set using_integration = false
                    #                     where ownerid=%s
                    #                     and service_id in %s
                    #                     and using_integration;""",
                    #                 ownerid, repo_service_ids)
                    db_session.query(Repository).filter(
                        Repository.ownerid == ownerid,
                        Repository.service_id.in_(repo_service_ids),
                        Repository.using_integration.is_(True) # TODO: ????
                    ).update({
                        Repository.using_integration: False
                    }, synchronize_session=False)
            else:
                # self.db.query("""UPDATE repos
                #                     set using_integration=false
                #                     where ownerid=%s
                #                     and using_integration;""",
                #                 ownerid)
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
            log.info(
                'repos: {}'.format(len(repos)),
                extra=dict(ownerid=ownerid, username=username, repos=repos)
            )
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
            # self.db.query("""UPDATE owners
            #                     set permission=(select array(select distinct unnest(permission || %s::int[]) order by 1))
            #                     where ownerid=%s;""",
            #                 private_project_ids, ownerid)
            owner.permission = sorted(map(int, list(set(owner.permission + private_project_ids))))

            #  choose a bot
            if private_project_ids:
                self.choose_bot(db_session, ownerid, service, owners_by_id)


    def upsert_owner(self, db_session, service, service_id, username, plan_provider=None):
        log.info(
            'upserting owner - service: {}, service_id: {}, username: {}'.format(service, service_id, username)
        )
        # owner = self.db.get("""SELECT ownerid, username
        #                        from owners
        #                        where service=%s
        #                          and service_id=%s
        #                        limit 1;""",
        #                     service, str(service_id))
        owner = db_session.query(Owner).filter(
            Owner.service == service,
            Owner.service_id == str(service_id)
        ).first()

        if owner:
            log.info(
                'upserting owner - found'
            )
            if (owner.username or '').lower() != username.lower():
                # self.db.query("UPDATE owners set username=%s where ownerid=%s;",
                #               owner['username'], owner['ownerid'])
                owner.username = username # TODO: ????
        else:
            log.info(
                'upserting owner - NOT found'
            )
            # insert owner
            # owner = self.db.get("""INSERT INTO owners (service, service_id, username, plan_provider)
            #                        values (%s, %s, %s, %s)
            #                        returning ownerid;""",
            #                     service, str(service_id), username, plan_provider)
            owner = Owner(
                service=service,
                service_id=str(service_id),
                username=username,
                plan_provider=plan_provider
            )
            db_session.add(owner)
            
        return owner.ownerid


    def upsert_repo(self, db_session, service, ownerid, repo_data, using_integration=None):
        log.info(
            'upserting repo {}'.format(repo_data)
        )
        # update repo information
        # res = self.db.get("""UPDATE repos
        #                      set private = %s,
        #                          language = %s,
        #                          name = %s,
        #                          deleted = false,
        #                          updatestamp = now()
        #                     where ownerid = %s
        #                      and service_id = %s
        #                     returning repoid;""",
        #                   repo['private'],
        #                   repo['language'],
        #                   repo['name'],
        #                   ownerid,
        #                   str(repo['service_id']))
        repo = db_session.query(Repository).filter(
            Repository.ownerid == ownerid,
            Repository.service_id == str(repo_data['service_id'])
        ).first()

        if repo:
            log.info('upserting repo - found')
            repo.private = repo_data['private']
            repo.language = repo_data['language']
            repo.name = repo_data['name']
            repo.deleted = False
            repo.updatestamp = datetime.now()
            repo_id = repo.repoid

        else:
            log.info('upserting repo - NOT found')
            # repo was not found, could be a different owner
            # res = self.db.get("""SELECT repoid
            #                      from repos r
            #                      inner join owners o using (ownerid)
            #                      where r.service_id=%s
            #                        and o.service=%s
            #                      limit 1;""",
            #                   str(repo['service_id']), service)
            repo_id = db_session.query(Repository.repoid).join(
                Owner, Repository.ownerid == Owner.ownerid
            ).filter(
                Repository.service_id == str(repo_data['service_id']),
                Repository.service == service
            ).first()
            if repo_id:
                log.info('upserting repo - repo exists but wrong owner')
                try:
                    # TODO: from here to end of function
                    # repo exists, but wrong owner
                    # res = self.db.get("""UPDATE repos
                    #                      set private = %s,
                    #                          language = %s,
                    #                          name = %s,
                    #                          deleted = false,
                    #                          updatestamp = now(),
                    #                          ownerid = %s
                    #                     where repoid = %s
                    #                     returning repoid;""",
                    #                   repo['private'],
                    #                   repo['language'],
                    #                   repo['name'],
                    #                   ownerid,
                    #                   res['repoid'])
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
                    # TODO: use ORM for this query
                    self.db.query("""UPDATE repos
                                     set service_id = %s,
                                         deleted = false,
                                         updatestamp = now(),
                                         private = %s
                                     where ownerid=%s
                                       and name=%s;""",
                                  repo['service_id'], repo['private'],
                                  ownerid, repo['name'])
            else:
                # repo does not exist, create it
                # res = self.db.get("""INSERT INTO repos (ownerid, service_id, name, language, private, branch, using_integration)
                #                      values (%s, %s, %s, %s, %s, %s, %s)
                #                      on conflict (ownerid, name) do update
                #                        set service_id=%s,
                #                            name=%s,
                #                            language=%s,
                #                            private=%s,
                #                            using_integration=%s
                #                      returning repoid;""",
                #                   ownerid,
                #                   str(repo['service_id']),
                #                   repo['name'],
                #                   repo['language'],
                #                   repo['private'],
                #                   repo['branch'],
                #                   using_integration,
                #                   str(repo['service_id']),
                #                   repo['name'],
                #                   repo['language'],
                #                   repo['private'],
                #                   using_integration)
                log.info(
                    'upserting repo - repo does not exist, create it',
                    extra=dict(ownerid=ownerid, repo_name=repo_data['name'])
                )
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

                res = db_session.execute(i).fetchall()
                [(new_repoid,)] = res
                log.info(
                    'res {}'.format(new_repoid),
                    extra=dict(res=res, new_repoid=new_repoid)
                )
                repo_id = new_repoid

        return repo_id


    def choose_bot(self, db_session, ownerid, service, owners_by_id):
        owners_by_id = map(str, owners_by_id.values())
        # remove me
        if str(ownerid) in owners_by_id:
            owners_by_id.remove(str(ownerid))

        if owners_by_id and (
            not self.enterprise or  # is production
            get_config((service, 'bot')) is None  # or no bot is set in yaml
        ):
            # we can see private repos, make me the bot
            # self.db.query("""UPDATE owners
            #                     set bot=%s
            #                     where service=%s
            #                     and ownerid in %s
            #                     and bot is null
            #                     and oauth_token is null;""",
            #                 ownerid, service, tuple(owners_by_id))
            db_session.query(Owner).filter(
                Owner.service == service,
                Owner.ownerid.in_(tuple(owners_by_id)),
                Owner.bot_id.is_(None),
                Owner.oauth_token.is_(None)
            ).update({
                Owner.bot_id: ownerid
            }, synchronize_session=False)


RegisteredSyncReposTask = celery_app.register_task(SyncReposTask())
sync_repos_task = celery_app.tasks[SyncReposTask.name]
