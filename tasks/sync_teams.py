import logging
from datetime import datetime
from json import dumps
from sqlalchemy.dialects.postgresql import insert

from app import celery_app
from celery_config import sync_teams_task_name
from tasks.base import BaseCodecovTask
from database.models import Owner
import torngit

from helpers.config import get_verify_ssl, get_config
from services.github import get_github_integration_token
from services.encryption import encryptor


log = logging.getLogger(__name__)


class SyncTeamsTask(BaseCodecovTask):
    """This task syncs the orgs/teams that a user belongs to
    """
    name = sync_teams_task_name

    def write_to_db(self):
        return True

    async def run_async(self, db_session, ownerid, username=None, using_integration=False, *args, **kwargs):
        owner = db_session.query(Owner).filter(
            Owner.ownerid == ownerid
        ).first()

        assert owner, 'User not found'
        service = owner.service

        log.info(
            "Sync teams",
            extra=dict(ownerid=ownerid, username=username, using_integration=using_integration)
        )

        token = self.create_token(owner, service, using_integration)
        oauth_consumer_token = dict(key=get_config((service, 'client_id')),
                                    secret=get_config((service, 'cliend_secret')))

        git = torngit.get(service,
                          token=token,
                          verify_ssl=get_verify_ssl(service),
                          oauth_consumer_token=oauth_consumer_token)

        # get list of teams with username, name, email, id (service_id), etc
        teams = await git.list_teams()

        updated_teams = []

        for team in teams:
            data = dict(service_id=team['id'],
                        service=service,
                        username=team['username'],
                        name=team['name'],
                        email=team['email'],
                        avatar_url=team.get('avatar_url'),
                        parent_service_id=team.get('parent_id'),
                        updatestamp=datetime.now())

            i = insert(Owner) \
                     .values(data) \
                     .on_conflict_do_update(constraint='owner_service_ids', set_=data) \
                     .returning(Owner.ownerid)

            [(ownerid,)] = db_session.execute(i).fetchall()
            data['ownerid'] = ownerid
            updated_teams.append(data)

        team_ids = [team['ownerid'] for team in teams]

        owner.updatestamp = datetime.now()
        owner.organizations = team_ids

    def create_token(self, owner, service, using_integration=False):
        if using_integration:
            token = dict(key=get_github_integration_token(service, owner.integration_id))
        else:
            token = encryptor.decode(owner.oauth_token)

        return token


SyncTeamsTask = celery_app.register_task(SyncTeamsTask())
sync_teams_task = celery_app.tasks[SyncTeamsTask.name]
