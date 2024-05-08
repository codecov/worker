import logging

import requests
import shared.torngit as torngit
from shared.config import get_config

from services.github import get_github_integration_token

log = logging.getLogger(__name__)


class GitHubMarketplaceService(object):
    """
    Static ids for each of Codecov's plans on GitHub marketplace
    """

    LEGACY_PLAN_ID = 18
    CURRENT_PLAN_ID = 2147
    PER_USER_PLAN_ID = 3267

    def __init__(self):
        self._token = None
        self.use_stubbed = get_config(
            "services", "github_marketplace", "use_stubbed", default=False
        )

    def api(
        self,
        method,
        url,
        body=None,
        headers=None,
        params=None,
        auth_with_integration_token=True,
        **args,
    ):
        _headers = {
            "Accept": "application/vnd.github.valkyrie-preview+json",
            "User-Agent": "Codecov",
        }
        if auth_with_integration_token:
            _headers["Authorization"] = f"Bearer {self.get_integration_token()}"
        _headers.update(headers or {})

        method = (method or "GET").upper()

        if url.startswith("/"):
            base_url = torngit.Github.get_api_url()
            url = base_url + url

        if self.use_stubbed:
            # use stubbed endpoints for testing
            # https://developer.github.com/v3/apps/marketplace/#testing-with-stubbed-endpoints
            url = url.replace("marketplace_listing/", "marketplace_listing/stubbed/", 1)

        res = requests.request(method, url, headers=_headers, params=params)
        try:
            res.raise_for_status()
        except requests.exceptions.HTTPError:
            log.exception(
                "Github Marketplace Service Error",
                extra=dict(code=res.status_code, text=res.text),
            )
            raise
        return res.json()

    def get_integration_token(self):
        """
        Get GitHub app token
        """
        if not self._token:
            self._token = get_github_integration_token("github")

        return self._token

    @property
    def plan_ids(self):
        return [self.LEGACY_PLAN_ID, self.CURRENT_PLAN_ID, self.PER_USER_PLAN_ID]

    def get_account_plans(self, account_id):
        """
        Check if a GitHub account is associated with any Marketplace listing.

        Shows whether the user or organization account actively subscribes to a
        Codecov plan. When someone submits a plan change that won't be processed until
        the end of their billing cycle, you will also see the upcoming pending change.
        """
        return self.api("get", "/marketplace_listing/accounts/{}".format(account_id))

    def get_codecov_plans(self):
        """
        List all plans for Codecov Marketplace listing
        """
        return self.api("get", "/marketplace_listing/plans")

    def get_plan_accounts(self, page, plan_id):
        """
        List all GitHub accounts (user or organization) on a specific plan.
        """
        params = dict(page=page)
        return self.api(
            "get",
            "/marketplace_listing/plans/{}/accounts".format(plan_id),
            params=params,
        )

    def get_user(self, service_id):
        """
        Get GitHub user details
        """
        params = dict(
            client_id=get_config("github", "client_id"),
            client_secret=get_config("github", "client_secret"),
        )
        return self.api(
            "get",
            "/user/{}".format(service_id),
            params=params,
            auth_with_integration_token=False,
        )
