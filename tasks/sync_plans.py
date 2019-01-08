import requests
from tornado import gen

from app import config
from stripe import Stripe
from app.tasks.task import celery, TornadoTask
from tasks.base import BaseCodecovTask


class SyncPlans(BaseCodecovTask):

    async def run_async(self, db_session, sender=None, account=None, start_plan_page=None, sync_these_plans=None):
        # Make sure users exist
        if sender:
            # insert sender and account
            res = db_session.execute("UPDATE owners set username=%s where service='github' and service_id=%s returning true;",
                              sender['login'], str(sender['id']))
            if not res:
                self.db.query("""INSERT INTO owners (service, service_id, username, plan_provider)
                                 values ('github', %s, %s, 'github');""",
                              str(sender['id']), sender['login'])
        if account:
            res = db_session.execute("UPDATE owners set username=%s where service='github' and service_id=%s returning true;",
                              account['login'], str(account['id']))
            if not res:
                self.db.query("""INSERT INTO owners (service, service_id, username, plan_provider)
                                 values ('github', %s, %s, 'github');""",
                              str(account['id']), account['login'])

        headers = {
           'Accept': 'application/vnd.github.valkyrie-preview+json',
           'User-Agent': 'Codecov',
           'Authorization': 'Bearer %s' % self.get_github_integration_token('github')
        }

        oauth_headers = {
           'User-Agent': 'Codecov'
        }

        oauth_args = 'client_id={}&client_secret={}'.format(
            config.get(('github', 'client_id')),
            config.get(('github', 'client_secret'))
        )

        # sync one
        if account:
            # TODO sync all team members

            # Get all the sender plans
            res = requests.get('https://api.github.com/marketplace_listing/accounts/%s' % account['id'],
                               headers=headers)
            if res.status_code == 404:
                await self.sync_plan(
                    account['id'],
                    None,
                    headers, oauth_headers, oauth_args
                )
            else:
                res.raise_for_status()
                await self.sync_plan(
                    account['id'],
                    res.json()['marketplace_purchase'],
                    headers, oauth_headers, oauth_args
                )

        # sync many
        else:
            has_a_plan = []
            # get codecov plans
            if not sync_these_plans:
                res = requests.get('https://api.github.com/marketplace_listing/plans',
                                   headers=headers)
                res.raise_for_status()
                plans = [plan['id'] for plan in res.json()]
            else:
                plans = sync_these_plans

            # loop through the plans
            for planid in plans:
                page = start_plan_page or 0
                # loop through all plan accounts
                while True:
                    page = page + 1
                    res = requests.get('https://api.github.com/marketplace_listing/plans/%s/accounts' % planid,
                                       params={'page': page},
                                       headers=headers)
                    res.raise_for_status()
                    body = res.json()

                    if len(body) == 0:
                        # next plan
                        break

                    # sync each plan
                    for customers in body:
                        has_a_plan.append(str(customers['id']))
                        await self.sync_plan(
                            customers['id'],
                            customers['marketplace_purchase'],
                            headers, oauth_headers, oauth_args
                        )

            if not sync_these_plans:
                # disable plan that were startted at GitHub but no longer active
                self.db.query("""UPDATE owners
                                 set plan = null
                                 where service = 'github'
                                   and plan = 'users'
                                   and plan_provider = 'github'
                                   and service_id not in %s;""",
                              tuple(has_a_plan))

    async def sync_plan(self, service_id, purchase_object, headers, oauth_headers, oauth_args):
        if not purchase_object:
            owner = db_session.execute("""UPDATE owners
                                   set plan = null,
                                       plan_user_count = 0,
                                       plan_activated_users = null
                                   where service = 'github'
                                     and service_id = %s
                                   returning ownerid;""",
                                str(service_id))
            if not owner:
                res = requests.get('https://api.github.com/user/{}?{}'.format(service_id, oauth_args),
                                   headers=oauth_headers)
                data = res.json()
                # create the user
                self.db.query("""INSERT INTO owners (service, service_id, username, name, email, plan_provider)
                                 values ('github', %s, %s, %s, 'github');""",
                              service_id, data['login'], data['name'], data['email'])
            else:
                # deactivate repos
                self.db.query("""UPDATE repos
                                 set activated = false
                                 where ownerid = %s;""",
                              owner['ownerid'])

        elif purchase_object['plan']['id'] == 18:
            # add plan to owner
            res = db_session.execute("""UPDATE owners
                                 set plan = 'users',
                                     plan_provider = 'github',
                                     plan_auto_activate = true,
                                     plan_user_count = %s
                                 where service = 'github'
                                   and service_id = %s
                                 returning ownerid, stripe_customer_id, stripe_subscription_id;""",
                              purchase_object['unit_count'],
                              str(service_id))
            if not res:
                res = requests.get('https://api.github.com/user/{}?{}'.format(service_id, oauth_args),
                                   headers=oauth_headers)
                # create the user
                data = res.json()
                self.db.query("""INSERT INTO owners (service, service_id, username, name, email, plan, plan_provider, plan_auto_activate, plan_user_count)
                                 values ('github', %s, %s, %s, %s, 'users', 'github', true, %s);""",
                              service_id, data['login'], data['name'], data['email'], purchase_object['unit_count'])

            # end stripe subscription
            elif res['stripe_customer_id'] and res['stripe_subscription_id']:
                stripe = Stripe(config.get(('services', 'stripe', 'api_key')))
                status, data = yield stripe.customers[res['stripe_customer_id']]\
                                           .subscriptions[res['stripe_subscription_id']]\
                                           .delete()
                self.db.query("""UPDATE owners
                                 set stripe_subscription_id = null
                                 where ownerid = %s;""",
                              res['ownerid'])
        else:
            # free plan
            res = db_session.execute("""UPDATE owners
                                 set plan = case when plan = 'users' then null else plan end,
                                     plan_user_count = 0
                                 where service = 'github'
                                   and service_id = %s
                                 returning ownerid;""",
                              str(service_id))
            if res:
                self.db.query("UPDATE repos set activated=false where ownerid=%s;",
                              res['ownerid'])
            else:
                res = requests.get('https://api.github.com/user/{}?{}'.format(service_id, oauth_args),
                                   headers=oauth_headers)
                # create the user
                data = res.json()
                self.db.query("""INSERT INTO owners (service, service_id, username, name, email, plan_provider, plan_auto_activate)
                                 values ('github', %s, %s, %s, %s, 'github', true);""",
                              service_id, data['login'], data['name'], data['email'])