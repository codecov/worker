import logging
import copy

log = logging.getLogger(__name__)


def get_repo_yaml(repository):
    return merge_yamls(repository.owner.yaml, repository.yaml)


def merge_yamls(owner_yaml, repo_yaml, commit_yaml=None):
    default_yaml = {}
    if commit_yaml is not None:
        return copy.deepcopy(commit_yaml)
    if repo_yaml is not None:
        return copy.deepcopy(repo_yaml)
    if owner_yaml is not None:
        return copy.deepcopy(owner_yaml)
    return copy.deepcopy(default_yaml)


def save_repo_yaml_to_database_if_needed(current_commit, new_yaml):
    repository = current_commit.repository
    existing_yaml = get_repo_yaml(repository)
    print(existing_yaml)
    syb = read_yaml_field(existing_yaml, ('codecov', 'strict_yaml_branch'))
    branches_considered_for_yaml = (
        syb,
        current_commit.repository.branch,
        read_yaml_field(existing_yaml, ('codecov', 'branch'))
    )
    if current_commit.branch and current_commit.branch in branches_considered_for_yaml:
        if not syb or syb == current_commit.branch:
            yaml_branch = read_yaml_field(new_yaml, ('codecov', 'branch'))
            if yaml_branch:
                repository.branch = yaml_branch
            repository.yaml = new_yaml
            log.info('Updated project yaml cache on commit %s', current_commit.commitid)
            return True
    return False


def read_yaml_field(yaml_dict, keys, _else=None):
    try:
        for key in keys:
            if hasattr(yaml_dict, '_asdict'):
                # namedtuples
                yaml_dict = getattr(yaml_dict, key)
            elif hasattr(yaml_dict, '__getitem__'):
                yaml_dict = yaml_dict[key]
            else:
                yaml_dict = getattr(yaml_dict, key)
        return yaml_dict
    except (AttributeError, KeyError):
        return _else
