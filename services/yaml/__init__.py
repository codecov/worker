import logging
import copy

from database.models import Commit
from covreports.config import get_config
from covreports.validation.exceptions import InvalidYamlException
from torngit.exceptions import TorngitClientError, TorngitError

from services.yaml.reader import read_yaml_field
from services.yaml.fetcher import fetch_commit_yaml_from_provider

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


async def get_current_yaml(commit: Commit, repository_service) -> dict:
    """
        Fetches what the current yaml is supposed to be

        This function wraps the whole logic of fetching the current yaml for a given commit
            - It makes best effort in trying to fetch and parse the data from the repo
            - It merges it with the owner YAML and with the default system YAML as needed
            - It handles possible exceptions that come from fetching data from the repository

    Args:
        commit (Commit): The commit we want to get the provider from
        repository_service : The service (as fetched from get_repo_provider_service) that we can use
            to fetch the YAML data. If None, we just pretend the YAML data isn't fetchable

    Returns:
        dict: The yaml, parsed, processed and ready to use as the final yaml
    """
    commit_yaml = None
    repository = commit.repository
    try:
        commit_yaml = await fetch_commit_yaml_from_provider(commit, repository_service)
    except InvalidYamlException as ex:
        log.warning(
            "Unable to use yaml from commit because it is invalid",
            extra=dict(
                repoid=repository.repoid,
                commit=commit.commitid,
                error_location=ex.error_location
            ),
            exc_info=True
        )
    except TorngitClientError:
        log.warning(
            "Unable to use yaml from commit because it cannot be fetched due to client issues",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True
        )
    except TorngitError:
        log.warning(
            "Unable to use yaml from commit because it cannot be fetched due unknown issues",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True
        )
    return get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml,
        commit_yaml=commit_yaml
    )


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
