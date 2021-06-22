import logging
from typing import Sequence, Mapping, Any
import shared.torngit as torngit
from shared.yaml import (
    fetch_current_yaml_from_provider_via_reference as shared_fetch_current_yaml_from_provider_via_reference,
)

from helpers.cache import cache
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
    return parse_yaml_file(yaml_content)
