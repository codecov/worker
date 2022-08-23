import logging

from shared.analytics_tracking import (
    track_betaprofiling_added_in_YAML,
    track_betaprofiling_removed_from_YAML,
    track_show_critical_paths_added_in_YAML,
    track_show_critical_paths_removed_from_YAML,
)
from shared.torngit.exceptions import TorngitClientError, TorngitError
from shared.validation.exceptions import InvalidYamlException
from shared.yaml import UserYaml

from database.models import Commit
from helpers.environment import is_enterprise
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from services.yaml.reader import read_yaml_field

log = logging.getLogger(__name__)


def get_repo_yaml(repository):
    return UserYaml.get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml,
        ownerid=repository.owner.ownerid,
    )


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
                error_location=ex.error_location,
            ),
            exc_info=True,
        )
    except TorngitClientError:
        log.warning(
            "Unable to use yaml from commit because it cannot be fetched due to client issues",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True,
        )
    except TorngitError:
        log.warning(
            "Unable to use yaml from commit because it cannot be fetched due to unknown issues",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True,
        )
    return UserYaml.get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml,
        commit_yaml=commit_yaml,
        ownerid=repository.owner.ownerid,
    )


def save_repo_yaml_to_database_if_needed(current_commit, new_yaml):
    repository = current_commit.repository
    existing_yaml = get_repo_yaml(repository)
    syb = read_yaml_field(existing_yaml, ("codecov", "strict_yaml_branch"))
    branches_considered_for_yaml = (
        syb,
        current_commit.repository.branch,
        read_yaml_field(existing_yaml, ("codecov", "branch")),
    )
    tracking_yaml_fields(existing_yaml, new_yaml, repository)
    if current_commit.branch and current_commit.branch in branches_considered_for_yaml:
        if not syb or syb == current_commit.branch:
            yaml_branch = read_yaml_field(new_yaml, ("codecov", "branch"))
            if yaml_branch:
                repository.branch = yaml_branch
            repository.yaml = new_yaml
            return True
    return False


def tracking_yaml_fields(existing_yaml, new_yaml, repository):
    track_betaprofiling(existing_yaml, new_yaml, repository)
    track_show_critical_paths(existing_yaml, new_yaml, repository)


def track_betaprofiling(existing_yaml, new_yaml, repository):
    existing_comment_layout_field = read_yaml_field(
        existing_yaml, ("comment", "layout")
    )
    new_comment_layout_field = read_yaml_field(new_yaml, ("comment", "layout"))

    existing_comment_sections = list(
        map(lambda l: l.strip(), (existing_comment_layout_field or "").split(","))
    )
    new_comment_sections = list(
        map(lambda l: l.strip(), (new_comment_layout_field or "").split(","))
    )

    if betaprofiling_is_added_in_yaml(existing_comment_sections, new_comment_sections):
        track_betaprofiling_added_in_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )

    if betaprofiling_is_removed_from_yaml(
        existing_comment_sections, new_comment_sections
    ):
        track_betaprofiling_removed_from_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )


def betaprofiling_is_added_in_yaml(existing_comment_sections, new_comment_sections):
    if (
        "betaprofiling" not in existing_comment_sections
        and "betaprofiling" in new_comment_sections
    ):
        return True
    return False


def betaprofiling_is_removed_from_yaml(existing_comment_sections, new_comment_sections):
    if (
        "betaprofiling" in existing_comment_sections
        and "betaprofiling" not in new_comment_sections
    ):
        return True
    return False


def track_show_critical_paths(existing_yaml, new_yaml, repository):
    existing_show_critical_paths = read_yaml_field(
        existing_yaml, ("comment", "show_critical_paths")
    )
    new_show_critical_paths = read_yaml_field(
        new_yaml, ("comment", "show_critical_paths")
    )

    if existing_show_critical_paths is None and new_show_critical_paths:
        track_show_critical_paths_added_in_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )
    if existing_show_critical_paths and new_show_critical_paths is None:
        track_show_critical_paths_removed_from_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )
