from time import time
import logging
from datetime import datetime
import requests
import jwt
import shared.torngit as torngit

from helpers.cache import cache
from helpers.exceptions import RepositoryWithoutValidBotError
from shared.config import get_config
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
            else torngit.GithubEnterprise.get_api_url()
        )
        headers = {
            "Accept": "application/vnd.github.machine-man-preview+json",
            "User-Agent": "Codecov",
            "Authorization": "Bearer %s" % token,
        }
        url = "%s/app/installations/%s/access_tokens" % (api_endpoint, integration_id)
        res = requests.post(url, headers=headers)
        if res.status_code in (404, 403):
            log.warning(
                "Integration could not be found to fetch token from or unauthorized",
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
        res_json = res.json()
        log.info(
            "Requested and received a Github Integration token",
            extra=dict(
                valid_from=datetime.fromtimestamp(payload["iat"]).isoformat(),
                expires_at=res_json.get("expires_at"),
                permissions=res_json.get("permissions"),
                repository_selection=res_json.get("repository_selection"),
                integration_id=integration_id,
            ),
        )
        return res_json["token"]
    else:
        return token
