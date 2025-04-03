import logging

import shared.torngit as torngit
from shared.helpers.cache import cache
from shared.yaml import (
    fetch_current_yaml_from_provider_via_reference as shared_fetch_current_yaml_from_provider_via_reference,
)

from database.models import Commit
from services.yaml.parser import parse_yaml_file

log = logging.getLogger(__name__)


@cache.cache_function()
async def fetch_commit_yaml_from_provider(
    commit: Commit, repository_service: torngit.base.TorngitBaseAdapter
) -> dict:
    yaml_content = await shared_fetch_current_yaml_from_provider_via_reference(
        commit.commitid, repository_service
    )
    if yaml_content:
        return parse_yaml_file(
            yaml_content,
            show_secrets_for=(
                commit.repository.service,
                commit.repository.owner.service_id,
                commit.repository.service_id,
            ),
        )
