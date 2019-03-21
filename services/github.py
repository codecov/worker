from time import time

import requests
import jwt

import torngit
from helpers.config import get_config


def get_github_integration_token(self, service, integration_id=None):
    # https://developer.github.com/early-access/integrations/authentication/
    now = int(time())
    payload = {
      # issued at time
      'iat': now,
      # JWT expiration time (max 10 minutes)
      'exp': now + int(get_config(service, 'integration', 'expires', default=500)),
      # Integration's GitHub identifier
      'iss': get_config(service, 'integration', 'id')
    }
    token = jwt.encode(payload, PEM[service], algorithm='RS256')
    if integration_id:
        api_endpoint = torngit.Github.api_url if service == 'github' else torngit.GithubEnterprise.api_url
        headers = {
            'Accept': 'application/vnd.github.machine-man-preview+json',
            'User-Agent': 'Codecov',
            'Authorization': 'Bearer %s' % token
        }
        url = '%s/app/installations/%s/access_tokens' % (api_endpoint, integration_id)
        res = requests.post(url, headers=headers)
        if res.status_code in (200, 201):
            return res.json()['token']
        else:
            self.log('error', 'Github Integration Error',
                     code=res.status_code,
                     text=res.text)
    else:
        return token
