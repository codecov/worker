import logging

import torngit

from helpers.config import get_config, get_verify_ssl
from services.encryption import decrypt_token
from services.bots import get_repo_appropriate_bot

log = logging.getLogger(__name__)


def get_repo_provider_service(repository, commit=None):
    _timeouts = [
        get_config('setup', 'http', 'timeouts', 'connect', default=15),
        get_config('setup', 'http', 'timeouts', 'receive', default=30)
    ]
    service = repository.owner.service
    bot = get_repo_appropriate_bot(repository)
    adapter_params = dict(
        repo=dict(name=repository.name, using_integration=repository.using_integration or False),
        owner=dict(
            service_id=repository.service_id,
            ownerid=repository.ownerid,
            username=repository.owner.username
        ),
        token=decrypt_token(bot.oauth_token),
        verify_ssl=get_verify_ssl(service),
        timeouts=_timeouts
    )
    return torngit.get(
        repository.service,
        **adapter_params
    )
