import logging

import shared.torngit as torngit
from shared.config import get_config, get_verify_ssl

from helpers.token_refresh import get_token_refresh_callback
from services.bots import get_owner_appropriate_bot_token

log = logging.getLogger(__name__)


def get_owner_provider_service(
    owner, using_integration=False, ignore_installation=False
):
    _timeouts = [
        get_config("setup", "http", "timeouts", "connect", default=15),
        get_config("setup", "http", "timeouts", "receive", default=30),
    ]
    service = owner.service
    token = get_owner_appropriate_bot_token(
        owner, using_integration, ignore_installation=ignore_installation
    )
    adapter_params = dict(
        owner=dict(
            service_id=owner.service_id, ownerid=owner.ownerid, username=owner.username
        ),
        token=token,
        verify_ssl=get_verify_ssl(service),
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=get_config(service, "client_id"),
            secret=get_config(service, "client_secret"),
        ),
        # if using integration we will use the integration token
        # not the owner's token
        on_token_refresh=(
            get_token_refresh_callback(owner) if not using_integration else None
        ),
    )
    return _get_owner_provider_service_instance(service, **adapter_params)


def _get_owner_provider_service_instance(service_name, **adapter_params):
    return torngit.get(service_name, **adapter_params)
