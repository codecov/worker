import logging

import shared.torngit as torngit
from shared.bots import get_adapter_auth_information
from shared.config import get_config, get_verify_ssl
from shared.django_apps.codecov_auth.models import Service
from shared.typings.torngit import (
    OwnerInfo,
    TorngitInstanceData,
)

from helpers.token_refresh import get_token_refresh_callback

log = logging.getLogger(__name__)


def get_owner_provider_service(owner, *, ignore_installation=False):
    _timeouts = [
        get_config("setup", "http", "timeouts", "connect", default=15),
        get_config("setup", "http", "timeouts", "receive", default=30),
    ]
    service = Service(owner.service)
    adapter_auth_info = get_adapter_auth_information(
        owner, ignore_installations=ignore_installation
    )
    data = TorngitInstanceData(
        owner=OwnerInfo(
            service_id=owner.service_id, ownerid=owner.ownerid, username=owner.username
        ),
        installation=adapter_auth_info["selected_installation_info"],
        fallback_installations=adapter_auth_info["fallback_installations"],
    )

    adapter_params = dict(
        token=adapter_auth_info["token"],
        verify_ssl=get_verify_ssl(service.value),
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=get_config(service, "client_id"),
            secret=get_config(service, "client_secret"),
        ),
        # if using integration we will use the integration token
        # not the owner's token
        on_token_refresh=get_token_refresh_callback(adapter_auth_info["token_owner"]),
        **data,
    )
    return _get_owner_provider_service_instance(service, **adapter_params)


def _get_owner_provider_service_instance(service_name, **adapter_params):
    return torngit.get(service_name, **adapter_params)
