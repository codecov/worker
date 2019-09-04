import logging
import copy

from helpers.config import get_config

log = logging.getLogger(__name__)


def get_repo_yaml(repository):
    return get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml
    )


def merge_yamls(d1, d2):
    if not isinstance(d1, dict) or not isinstance(d2, dict):
        return d2
    d1.update(dict([(k, merge_yamls(d1.get(k, {}), v)) for k, v in d2.items()]))
    return d1


def get_final_yaml(*, owner_yaml, repo_yaml, commit_yaml=None):
    """Given a owner yaml, repo yaml and user yaml, determines what yaml we need to use

    The answer is usually a "deep merge" between the site-level yaml, the
        owner yaml (which is set by them at the UI) and either one of commit_yaml or repo_yaml

    Why does repo_yaml gets overriden by commit_yaml, but owner_yaml doesn't?
        The idea is that the commit yaml is something at the repo level, which
            at sometime will be used to replace the current repo yaml.
        In fact, if that commit gets merged on master, then the old repo_yaml won't have any effect
            anymore. So this guarantees that if you set  yaml at a certain branch, when you merge
            that branch into master the yaml will continue to have the same effect.
        It would be a sucky behavior if your commit changes were you trying to get rid of a
            repo level yaml config and we were still merging them.

    Args:
        owner_yaml (nullable dict): The yaml that is on the owner level (ie at the owner table)
        repo_yaml (nullable dict): [description]
        commit_yaml (nullable dict): [description] (default: {None})

    Returns:
        dict - The dict we are supposed to use when concerning that user/commit
    """
    resulting_yaml = copy.deepcopy(get_config('site', default={}))
    if owner_yaml is not None:
        resulting_yaml = merge_yamls(resulting_yaml, owner_yaml)
    if commit_yaml is not None:
        return merge_yamls(resulting_yaml, commit_yaml)
    if repo_yaml is not None:
        return merge_yamls(resulting_yaml, repo_yaml)
    return resulting_yaml


def save_repo_yaml_to_database_if_needed(current_commit, new_yaml):
    repository = current_commit.repository
    existing_yaml = get_repo_yaml(repository)
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
            return True
    return False


def read_yaml_field(yaml_dict, keys, _else=None):
    log.debug("Field %s requested", keys)
    try:
        for key in keys:
            if hasattr(yaml_dict, '__getitem__'):
                yaml_dict = yaml_dict[key]
            else:
                yaml_dict = getattr(yaml_dict, key)
        return yaml_dict
    except (AttributeError, KeyError):
        return _else
