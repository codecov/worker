from time import time
import logging

import requests
import jwt
import torngit

from helpers.cache import cache
from helpers.exceptions import RepositoryWithoutValidBotError
from covreports.config import get_config
from services.pem import get_pem

log = logging.getLogger(__name__)


@cache.cache_function()
def get_github_integration_token(service, integration_id=None):
    # https://developer.github.com/apps/building-github-apps/authenticating-with-github-apps/
    now = int(time())
    payload = {
        # issued at time
        "iat": now,
        # JWT expiration time (max 10 minutes)
        "exp": now + int(get_config(service, "integration", "expires", default=500)),
        # Integration's GitHub identifier
        "iss": get_config(service, "integration", "id"),
    }
    token = jwt.encode(payload, get_pem(service), algorithm="RS256").decode()
    if integration_id:
        api_endpoint = (
            torngit.Github.api_url
            if service == "github"
            else torngit.GithubEnterprise.api_url
        )
        headers = {
            "Accept": "application/vnd.github.machine-man-preview+json",
            "User-Agent": "Codecov",
            "Authorization": "Bearer %s" % token,
        }
        url = "%s/app/installations/%s/access_tokens" % (api_endpoint, integration_id)
        res = requests.post(url, headers=headers)
        if res.status_code == 404:
            log.warning(
                "Integration could not be found to fetch token from",
                extra=dict(service=service, integration_id=integration_id),
            )
            raise RepositoryWithoutValidBotError()
        try:
            res.raise_for_status()
        except requests.exceptions.HTTPError:
            log.exception(
                "Github Integration Error on service %s",
                service,
                extra=dict(code=res.status_code, text=res.text),
            )
            raise
        return res.json()["token"]
    else:
        return token
