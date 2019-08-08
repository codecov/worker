import torngit

from services.yaml.parser import parse_yaml_file


async def fetch_commit_yaml_from_provider(commit, repository_service):
    try:
        location = 'codecov.yml'
        ref = commit.commitid
        return parse_yaml_file(await repository_service.get_source(location, ref))
    except torngit.exceptions.ObjectNotFoundException:
        return None
