import logging

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

    async def run_async(self, db_session, ownerid, username=None, using_integration=False, *args, **kwargs):
        owner = db_session.query(Owner).filter(
            Owner.ownerid == ownerid
        ).first()

        assert owner, 'User not found'
        service = owner.service

        token = self.create_token(owner, service, using_integration)

        git = torngit.get(service,
                          token=token,
                          verify_ssl=get_verify_ssl(service),
                          oauth_consumer_token=dict(key=get_config((service, 'client_id')),
                                                    secret=get_config((service, 'cliend_secret'))))


    def create_token(self, owner, service, using_integration=False):
        if using_integration:
            token = dict(key=get_github_integration_token(service, owner.integration_id))
        else:
            token = encryptor.decode(owner.oauth_token)

        return token


SyncTeamsTask = celery_app.register_task(SyncTeamsTask())
sync_teams_task = celery_app.tasks[SyncTeamsTask.name]
