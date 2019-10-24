import logging

import torngit

from helpers.config import get_config, get_verify_ssl
from services.github import get_github_integration_token
from services.encryption import encryptor
from database.models import Owner

log = logging.getLogger(__name__)

def get_owner_token(owner, using_integration=False):
    if using_integration:
        token = dict(key=get_github_integration_token(owner.service, owner.integration_id))
    else:
        token = encryptor.decrypt_token(owner.oauth_token)

    return token

def get_owner_provider_service(owner, using_integration):
    _timeouts = [
        get_config('setup', 'http', 'timeouts', 'connect', default=15),
        get_config('setup', 'http', 'timeouts', 'receive', default=30)
    ]
    service = owner.service
    token = get_owner_token(owner, using_integration)
    adapter_params = dict(
        owner=dict(
            service_id=owner.service_id,
            ownerid=owner.ownerid,
            username=owner.username
        ),
        token=token,
        verify_ssl=get_verify_ssl(service),
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=get_config(service, 'client_id'),
            secret=get_config(service, 'client_secret')
        )
    )
    return _get_owner_provider_service_instance(service, **adapter_params)


def _get_owner_provider_service_instance(service_name, **adapter_params):
    return torngit.get(
        service_name,
        **adapter_params
    )
