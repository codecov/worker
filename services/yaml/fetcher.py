import logging
from typing import Sequence, Mapping, Any
import shared.torngit as torngit

from helpers.cache import cache
from database.models import Commit
from services.yaml.parser import parse_yaml_file

log = logging.getLogger(__name__)


@cache.cache_function()
async def fetch_commit_yaml_from_provider(
    commit: Commit, repository_service: torngit.base.TorngitBaseAdapter
) -> dict:
    return await fetch_current_yaml_from_provider_via_reference(
        commit.commitid, repository_service
    )


async def fetch_current_yaml_from_provider_via_reference(
    ref: str, repository_service: torngit.base.TorngitBaseAdapter
) -> dict:
    repoid = repository_service.data["repo"]["repoid"]
    location = await determine_commit_yaml_location(ref, repository_service)
    if not location:
        log.info(
            "We were not able to find the yaml on the provider API",
            extra=dict(commit=ref, repoid=repoid),
        )
        return None
    log.info(
        "Yaml was found on provider API",
        extra=dict(commit=ref, repoid=repoid, location=location),
    )
    try:
        content = await repository_service.get_source(location, ref)
        return parse_yaml_file(content["content"])
    except torngit.exceptions.TorngitObjectNotFoundError:
        log.exception(
            "File not in %s for commit", extra=dict(commit=ref, location=location)
        )
    return None


@cache.cache_function()
async def determine_commit_yaml_location(
    ref: str, repository_service: torngit.base.TorngitBaseAdapter
) -> str:
    """
        Determines where in `ref` the codecov.yaml is, in a given repository

        We currently look for the yaml in two different kinds of places
            - Root level of the rpeository
            - Specific folders that we know some customers use:
                - `dev`
                - `.github`

    Args:
        ref (str): The ref. Could be a branch name, tag, commit sha.
        repository_service (torngit.base.TorngitBaseAdapter): The torngit handler that can fetch this data.
            Indirectly determines the repository

    Returns:
        str: The path of the codecov.yaml file we found. Or `None,` if not found
    """
    possible_locations = [
        "codecov.yml",
        ".codecov.yml",
        "codecov.yaml",
        ".codecov.yaml",
    ]
    acceptable_folders = set(["dev", ".github"])
    top_level_files = await repository_service.list_top_level_files(ref)
    top_level_yaml = _search_among_files(possible_locations, top_level_files)
    if top_level_yaml is not None:
        return top_level_yaml
    all_folders = set(f["path"] for f in top_level_files if f["type"] == "folder")
    possible_folders = all_folders & acceptable_folders
    for folder in possible_folders:
        files_inside_folder = await repository_service.list_files(ref, folder)
        yaml_inside_folder = _search_among_files(
            possible_locations, files_inside_folder
        )
        if yaml_inside_folder:
            return yaml_inside_folder
    return None


def _search_among_files(
    desired_filenames: Sequence[str], all_files: Sequence[Mapping[str, Any]]
) -> str:
    for file in all_files:
        if (
            file.get("name") in desired_filenames
            or file.get("path").split("/")[-1] in desired_filenames
        ):
            return file["path"]
    return None
