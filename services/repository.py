import logging

import torngit

from helpers.config import get_config, get_verify_ssl
from services.encryption import decrypt_token
from services.yaml import get_repo_yaml
from services.bots import get_repo_appropriate_bot

log = logging.getLogger(__name__)


def get_repo_provider_service(repo, commit=None):
    _timeouts = [
        get_config('setup', 'http', 'timeouts', 'connect', default=15),
        get_config('setup', 'http', 'timeouts', 'receive', default=30)
    ]
    service = repo.owner.service
    bot = get_repo_appropriate_bot(repo)
    adapter_params = dict(
        repo=dict(name=repo.name, using_integration=repo.using_integration or False),
        yaml=get_repo_yaml(repo),
        owner=dict(
            service_id=repo.service_id,
            ownerid=repo.ownerid,
            username=repo.owner.username
        ),
        token=decrypt_token(bot.oauth_token),
        verify_ssl=get_verify_ssl(service),
        timeouts=_timeouts
    )
    return torngit.get(
        repo.service,
        **adapter_params
    )
