import logging

import torngit

from services.yaml.parser import parse_yaml_file

log = logging.getLogger(__name__)


async def fetch_commit_yaml_from_provider(commit, repository_service):
    possible_locations = [
        'codecov.yml',
        '.codecov.yml',
        'codecov.yaml',
        '.codecov.yaml'
    ]
    for location in possible_locations:
        try:
            ref = commit.commitid
            content = await repository_service.get_source(location, ref)
            return parse_yaml_file(content['content'])
        except torngit.exceptions.TorngitObjectNotFoundError:
            log.debug("File not in %s for commit", location)
    return None
