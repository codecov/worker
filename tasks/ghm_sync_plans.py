import logging
import requests
from datetime import datetime

from app import celery_app
from celery_config import ghm_sync_plans_task_name
from database.models import Owner
from services.github_marketplace import GitHubMarketplaceService
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

class SyncPlansTask(BaseCodecovTask):
    """
    Sync GitHub marketplace plans
    """
    name = ghm_sync_plans_task_name

    async def run_async(self, db_session, sender=None, account=None, action=None):
        log.info(
            'GitHub marketplace sync plans',
            extra=dict(sender=sender, account=account, action=action)
        )

        # Make sure sender and account owner entries exist
        if sender:
            self.upsert_owner(db_session, sender['id'], sender['login'])

        if account:
            self.upsert_owner(db_session, account['id'], account['login'])


        ghm = GitHubMarketplaceService()

        if account:
            # TODO sync all team members - probably need to ask eli if this is needed

            # Get all the sender plans
            try:
                plans = ghm.get_sender_plans(account['id'])
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    await self.sync_plan(
                        account['id'],
                        None,
                        action=action
                    )
                raise

            await self.sync_plan(
                account['id'],
                plans['marketplace_purchase'],
                action=action
            )
        else:
            has_a_plan = []

            # get codecov plans
            plans = ghm.get_codecov_plans()
            plans = [plan['id'] for plan in plans]

            # loop through the plans
            for plan_id in plans:
                page = 0
                # loop through all plan accounts
                while True:
                    page = page + 1
                    accounts = ghm.get_plan_accounts(page, plan_id)

                    if len(accounts) == 0:
                        # next plan
                        break

                    # sync each plan
                    for customers in accounts:
                        has_a_plan.append(str(customers['id']))
                        await self.sync_plan(
                            customers['id'],
                            customers['marketplace_purchase'],
                            action=action
                        )

            self.disable_inactive(db_session, has_a_plan)


    async def sync_plan(self, service_id, purchase_object, action=None):
        pass

    def upsert_owner(self, db_session, service_id, username):
        log.info(
            'Upserting owner',
            extra=dict(service_id=service_id, username=username)
        )
        owner = db_session.query(Owner).filter(
            Owner.service == 'github',
            Owner.service_id == str(service_id)
        ).first()

        if owner:
            owner.username = username
            owner.updatestamp = datetime.now()
        else:
            owner = Owner(
                service='github',
                service_id=service_id,
                username=username,
                plan_provider='github'
            )
            db_session.add(owner)
            db_session.flush()

        return owner.ownerid

    def disable_inactive(self, db_session, active_account_ids):
        """
        Disable plans that are no longer active
        """
        active_account_ids = list(map(str, active_account_ids))

        db_session.query(Owner).filter(
            Owner.service == 'github',
            Owner.plan == 'users',
            Owner.plan_provider == 'github',
            Owner.service_id.notin_(active_account_ids),
        ).update({
            Owner.plan: None
        }, synchronize_session=False)


RegisteredGHMSyncPlansTask = celery_app.register_task(SyncPlansTask())
ghm_sync_plans_task = celery_app.tasks[SyncPlansTask.name]
