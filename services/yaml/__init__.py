import logging

from shared.torngit.exceptions import TorngitClientError, TorngitError
from shared.validation.exceptions import InvalidYamlException
from shared.yaml import UserYaml

from database.enums import CommitErrorTypes
from database.models import Commit
from database.models.core import CommitError
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from services.yaml.reader import read_yaml_field

log = logging.getLogger(__name__)


def get_repo_yaml(repository):
    return UserYaml.get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml,
        ownerid=repository.owner.ownerid,
    )


def save_yaml_error(commit: Commit, code):
    try:
        db_session = commit.get_db_session()
        err = CommitError(commit=commit, error_code=code, error_params={})
        db_session.add(err)
        db_session.commit()
    except Exception as e:
        log.info("Error saving yaml commit error", e, code)


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
        save_yaml_error(commit, code=CommitErrorTypes.Yaml.value.INVALID_YAML.value)

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
        save_yaml_error(
            commit, code=CommitErrorTypes.Yaml.value.YAML_CLIENT_ERROR.value
        )

        log.warning(
            "Unable to use yaml from commit because it cannot be fetched due to client issues",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True,
        )
    except TorngitError:
        save_yaml_error(
            commit, code=CommitErrorTypes.Yaml.value.YAML_UNKNOWN_ERROR.value
        )

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
    if current_commit.branch and current_commit.branch in branches_considered_for_yaml:
        if not syb or syb == current_commit.branch:
            yaml_branch = read_yaml_field(new_yaml, ("codecov", "branch"))
            if yaml_branch:
                repository.branch = yaml_branch
            repository.yaml = new_yaml
            return True
    return False
