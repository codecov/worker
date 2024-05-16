import logging

import shared.torngit as torngit
from shared.config import get_config, get_verify_ssl
from shared.typings.torngit import (
    GithubInstallationInfo,
    OwnerInfo,
    TorngitInstanceData,
)

from helpers.token_refresh import get_token_refresh_callback
from services.bots import get_owner_appropriate_bot_token, get_owner_installation_id

log = logging.getLogger(__name__)


def get_owner_provider_service(
    owner, using_integration=False, ignore_installation=False
):
    _timeouts = [
        get_config("setup", "http", "timeouts", "connect", default=15),
        get_config("setup", "http", "timeouts", "receive", default=30),
    ]
    service = owner.service
    installation_info = get_owner_installation_id(
        owner, using_integration, ignore_installation=ignore_installation
    )
    token = get_owner_appropriate_bot_token(owner, installation_dict=installation_info)
    data = TorngitInstanceData(
        owner=OwnerInfo(
            service_id=owner.service_id, ownerid=owner.ownerid, username=owner.username
        ),
        installation=None,
        fallback_installations=None,
    )
    if installation_info:
        data["installation"] = GithubInstallationInfo(
            installation_id=installation_info.get("installation_id"),
            app_id=installation_info.get("app_id"),
            pem_path=installation_info.get("pem_path"),
        )
        data["fallback_installations"] = installation_info.get("fallback_installations")

    adapter_params = dict(
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
        **data,
    )
    return _get_owner_provider_service_instance(service, **adapter_params)


def _get_owner_provider_service_instance(service_name, **adapter_params):
    return torngit.get(service_name, **adapter_params)
