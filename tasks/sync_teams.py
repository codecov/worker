import logging
from datetime import datetime

from asgiref.sync import async_to_sync
from shared.celery_config import sync_teams_task_name

from app import celery_app
from database.models import Owner
from services.owner import get_owner_provider_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class SyncTeamsTask(BaseCodecovTask, name=sync_teams_task_name):
    """This task syncs the orgs/teams that a user belongs to"""

    ignore_result = False

    def run_impl(self, db_session, ownerid, *, username=None, **kwargs):
        log.info("Sync teams", extra=dict(ownerid=ownerid, username=username))
        owner = db_session.query(Owner).filter(Owner.ownerid == ownerid).first()

        assert owner, "Owner not found"
        service = owner.service

        git = get_owner_provider_service(owner, ignore_installation=True)

        # get list of teams with username, name, email, id (service_id), etc
        teams = async_to_sync(git.list_teams)()

        updated_teams = []

        for team in teams:
            team_data = dict(
                username=team["username"],
                name=team["name"],
                email=team.get("email"),
                avatar_url=team.get("avatar_url"),
                parent_service_id=team.get("parent_id"),
            )
            team_ownerid = self.upsert_team(
                db_session, service, str(team["id"]), team_data
            )
            team_data["ownerid"] = team_ownerid
            updated_teams.append(team_data)

        team_ids = [team["ownerid"] for team in updated_teams]

        removed_orgs = set(owner.organizations or []) - set(team_ids)
        if removed_orgs:
            log.warning(
                "Owner had access to organization that are being removed",
                extra=dict(
                    old_orgs=owner.organizations,
                    new_orgs=team_ids,
                    removed_orgs=sorted(removed_orgs),
                    ownerid=ownerid,
                ),
            )
            for org in removed_orgs:
                org.plan_activated_users.remove(ownerid)

        owner.updatestamp = datetime.now()
        owner.organizations = team_ids

    def upsert_team(self, db_session, service, service_id, data):
        log.info(
            "Upserting team",
            extra=dict(git_service=service, service_id=service_id, data=data),
        )
        team = (
            db_session.query(Owner)
            .filter(Owner.service == service, Owner.service_id == str(service_id))
            .first()
        )

        if team:
            team.username = data["username"]
            team.name = data["name"]
            team.email = data.get("email")
            team.avatar_url = data.get("avatar_url")
            team.parent_service_id = data.get("parent_service_id")
            team.updatestamp = datetime.now()
        else:
            team = Owner(
                service=service,
                service_id=service_id,
                username=data["username"],
                name=data["name"],
                email=data.get("email"),
                avatar_url=data.get("avatar_url"),
                parent_service_id=data.get("parent_service_id"),
                createstamp=datetime.now(),
            )
            db_session.add(team)
            db_session.flush()

        return team.ownerid


RegisteredSyncTeamsTask = celery_app.register_task(SyncTeamsTask())
sync_teams_task = celery_app.tasks[SyncTeamsTask.name]
