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
            data = dict(service_id=team['id'],
                        service=service,
                        username=team['username'],
                        name=team['name'],
                        email=team.get('email'),
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


RegisteredSyncTeamsTask = celery_app.register_task(SyncTeamsTask())
sync_teams_task = celery_app.tasks[SyncTeamsTask.name]
