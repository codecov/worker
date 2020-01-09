import logging

import torngit

from services.yaml.parser import parse_yaml_file

log = logging.getLogger(__name__)


async def fetch_commit_yaml_from_provider(commit, repository_service):
    return await fetch_current_yaml_from_provider_via_reference(commit.commitid, repository_service)


async def fetch_current_yaml_from_provider_via_reference(ref, repository_service):
    repoid = repository_service.data['repo']['repoid']
    location = await determine_commit_yaml_location(ref, repository_service)
    if not location:
        log.info(
            "We were not able to find the yaml on the provider API",
            extra=dict(
                commit=ref,
                repoid=repoid
            )
        )
        return None
    log.info(
        "Yaml was found on provider API",
        extra=dict(
            commit=ref,
            repoid=repoid,
            location=location
        )
    )
    try:
        content = await repository_service.get_source(location, ref)
        return parse_yaml_file(content['content'])
    except torngit.exceptions.TorngitObjectNotFoundError:
        log.exception(
            "File not in %s for commit",
            extra=dict(commit=ref, location=location)
        )
    return None


async def determine_commit_yaml_location(ref, repository_service):
    possible_locations = [
        'codecov.yml',
        '.codecov.yml',
        'codecov.yaml',
        '.codecov.yaml'
    ]
    top_level_files = await repository_service.list_top_level_files(ref)
    filenames = set(file_dict['path'] for file_dict in top_level_files)
    for possibility in possible_locations:
        if possibility in filenames:
            return possibility
    return None