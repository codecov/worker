import logging
import requests

import torngit
from services.github import get_github_integration_token

log = logging.getLogger(__name__)


class GitHubMarketplaceService(object):

    LEGACY_PLAN_ID = 18
    CURRENT_PLAN_ID = 2147
    PER_USER_PLAN_ID = 3267

    def __init__(self):
        self._token = None

    async def api(self,
                  method,
                  url,
                  body=None,
                  headers=None,
                  params=None,
                  **args):
        _headers = {
           'Accept': 'application/vnd.github.valkyrie-preview+json',
           'User-Agent': 'Codecov',
           'Authorization': 'Bearer %s' % self.get_integration_token()
        }
        _headers.update(headers or {})
        method = (method or 'GET').upper()
        base_url = torngit.Github.api_url
        if url.startswith('/'): 
            url = base_url + url
        
        res = requests.request(method, url, headers=_headers, params=params)
        try:
            res.raise_for_status()
        except requests.exceptions.HTTPError:
            log.exception(
                'Github Marketplace Error',
                extra=dict(
                    code=res.status_code,
                    text=res.text
                )
            )
            raise
        return res.json()

    def get_integration_token(self):
        if not self._token:
            self._token = get_github_integration_token('github')

        return self._token

    def get_sender_plans(self, account_id):
        return self.api('get', '/marketplace_listing/accounts/{}'.format(account_id))
    
    def get_codecov_plans(self):
        return self.api('get', '/marketplace_listing/plans')
    
    def get_plan_accounts(self, page, plan_id):
        params = dict(page=page)
        return self.api('get', '/marketplace_listing/plans/{}/accounts'.format(plan_id), params=params)

    @property
    def plan_ids(self):
        return list(self.LEGACY_PLAN_ID, self.CURRENT_PLAN_ID, self.PER_USER_PLAN_ID)
