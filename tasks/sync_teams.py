import logging
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert

from app import celery_app
from celery_config import sync_teams_task_name
from tasks.base import BaseCodecovTask
from database.models import Owner
from services.owner import get_owner_provider_service

log = logging.getLogger(__name__)


class SyncTeamsTask(BaseCodecovTask):
    """This task syncs the orgs/teams that a user belongs to
    """
    name = sync_teams_task_name

    def write_to_db(self):
        return True

    async def run_async(self, db_session, ownerid, *, username=None, using_integration=False, **kwargs):
        log.info(
            'Sync teams',
            extra=dict(ownerid=ownerid, username=username, using_integration=using_integration)
        )
        owner = db_session.query(Owner).filter(
            Owner.ownerid == ownerid
        ).first()

        assert owner, 'Owner not found'
        service = owner.service

        git = get_owner_provider_service(owner, using_integration)

        # get list of teams with username, name, email, id (service_id), etc
        teams = await git.list_teams()

        updated_teams = []

        for team in teams:
            team_data = dict(
                username=team['username'],
                name=team['name'],
                email=team.get('email'),
                avatar_url=team.get('avatar_url'),
                parent_service_id=team.get('parent_id')
            )
            team_ownerid = self.upsert_team(db_session, service, str(team['id']), team_data)
            team_data['ownerid'] = team_ownerid
            updated_teams.append(team_data)

        team_ids = [team['ownerid'] for team in updated_teams]

        owner.updatestamp = datetime.now()
        owner.organizations = team_ids

    def upsert_team(self, db_session, service, service_id, data):
        log.info(
            'upserting team',
            extra=dict(service=service, service_id=service_id, data=data)
        )
        team = db_session.query(Owner).filter(
            Owner.service == service,
            Owner.service_id == str(service_id)
        ).first()

        if team:
            team.username = data['username'],
            team.name = data['name'],
            team.email = data.get('email'),
            team.avatar_url = data.get('avatar_url'),
            team.parent_service_id = data.get('parent_service_id'),
            team.updatestamp = datetime.now()
        else:
            team = Owner(
                service=service,
                service_id=service_id,
                username=data['username'],
                name=data['name'],
                email=data.get('email'),
                avatar_url=data.get('avatar_url'),
                parent_service_id=data.get('parent_service_id')
            )
            db_session.add(team)
        db_session.flush()
        return team.ownerid


RegisteredSyncTeamsTask = celery_app.register_task(SyncTeamsTask())
sync_teams_task = celery_app.tasks[SyncTeamsTask.name]
