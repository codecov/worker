import logging
from typing import List, Optional

from shared.django_apps.codecov_auth.models import Service
from shared.typings.torngit import GithubInstallationInfo

from database.models import Owner, Repository
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from services.bots.github_apps import get_github_app_info_for_owner
from services.bots.owner_bots import get_owner_appropriate_bot_token
from services.bots.public_bots import get_token_type_mapping
from services.bots.repo_bots import get_repo_appropriate_bot_token
from services.bots.types import (
    AdapterAuthInformation,
)

log = logging.getLogger(__name__)


def get_adapter_auth_information(
    owner: Owner,
    repository: Optional[Repository] = None,
    *,
    ignore_installations: bool = False,
    installation_name_to_use: str | None = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
) -> AdapterAuthInformation:
    """Gets all the auth information needed to send requests to the provider"""
    installation_info: GithubInstallationInfo | None = None
    token_type_mapping = None
    fallback_installations: List[GithubInstallationInfo] | None = None
    if (
        Service(owner.service) in [Service.GITHUB, Service.GITHUB_ENTERPRISE]
        # in sync_teams and sync_repos we might prefer to use the owner's OAuthToken instead of installation
        and not ignore_installations
    ):
        installations_available_info = get_github_app_info_for_owner(
            owner,
            repository=repository,
            installation_name=installation_name_to_use,
        )
        if installations_available_info != []:
            installation_info, *fallback_installations = installations_available_info

    if repository:
        token, token_owner = get_repo_appropriate_bot_token(
            repository, installation_info
        )
        if installation_info is None:
            # the admin_bot_token should be associated with an Owner so we know that it was
            # actually configured for this Repository.
            # The exception would be GH installation tokens, but in that case we don't use token_type_mapping
            token_type_mapping = get_token_type_mapping(
                repository, admin_bot_token=(token if token_owner else None)
            )
    else:
        token, token_owner = get_owner_appropriate_bot_token(owner, installation_info)
    return AdapterAuthInformation(
        token=token,
        token_owner=token_owner,
        selected_installation_info=installation_info,
        fallback_installations=fallback_installations,
        token_type_mapping=token_type_mapping,
    )
