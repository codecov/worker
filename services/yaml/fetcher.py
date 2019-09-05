import logging

import torngit

from services.yaml.parser import parse_yaml_file

log = logging.getLogger(__name__)


async def fetch_commit_yaml_from_provider(commit, repository_service):
    location = await determine_commit_yaml_location(commit, repository_service)
    if not location:
        return None
    try:
        ref = commit.commitid
        content = await repository_service.get_source(location, ref)
        return parse_yaml_file(content['content'])
    except torngit.exceptions.TorngitObjectNotFoundError:
        log.exception(
            "File not in %s for commit",
            extra=dict(commit=commit.commitid, location=location)
        )
    return None


async def determine_commit_yaml_location(commit, repository_service):
    possible_locations = [
        'codecov.yml',
        '.codecov.yml',
        'codecov.yaml',
        '.codecov.yaml'
    ]
    top_level_files = await repository_service.list_top_level_files(commit.commitid)
    filenames = set(file_dict['path'] for file_dict in top_level_files)
    for possibility in possible_locations:
        if possibility in filenames:
            return possibility
    return None
