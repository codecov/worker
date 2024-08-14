import logging

from shared.torngit.exceptions import TorngitClientError, TorngitError
from shared.validation.exceptions import InvalidYamlException
from shared.yaml import UserYaml
from shared.yaml.user_yaml import OwnerContext, RepoContext

from database.enums import CommitErrorTypes
from database.models import Commit
from database.models.core import Repository
from helpers.save_commit_error import save_commit_error
from services.yaml.fetcher import fetch_commit_yaml_from_provider
from services.yaml.reader import read_yaml_field

log = logging.getLogger(__name__)


def get_repo_yaml(repository: Repository):
    owner_context = OwnerContext(
        owner_onboarding_date=repository.owner.createstamp,
        owner_plan=repository.owner.plan,
        ownerid=repository.ownerid,
    )
    repo_context = RepoContext(repo_creation_date=repository.created_at)
    return UserYaml.get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml,
        owner_context=owner_context,
        repo_context=repo_context,
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
        save_commit_error(
            commit,
            error_code=CommitErrorTypes.INVALID_YAML.value,
            error_params=dict(
                repoid=repository.repoid,
                commit_yaml=commit_yaml,
                error_location=ex.error_location,
            ),
        )

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
        save_commit_error(
            commit,
            error_code=CommitErrorTypes.YAML_CLIENT_ERROR.value,
            error_params=dict(
                repoid=repository.repoid,
                commit_yaml=commit_yaml,
            ),
        )

        log.warning(
            "Unable to use yaml from commit because it cannot be fetched due to client issues",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True,
        )
    except TorngitError:
        save_commit_error(
            commit,
            error_code=CommitErrorTypes.YAML_UNKNOWN_ERROR.value,
            error_params=dict(
                repoid=repository.repoid,
                commit_yaml=commit_yaml,
            ),
        )

        log.warning(
            "Unable to use yaml from commit because it cannot be fetched due to unknown issues",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True,
        )
    owner_context = OwnerContext(
        owner_onboarding_date=repository.owner.createstamp,
        owner_plan=repository.owner.plan,
        ownerid=repository.ownerid,
    )
    repo_context = RepoContext(repo_creation_date=repository.created_at)

    return UserYaml.get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml,
        commit_yaml=commit_yaml,
        owner_context=owner_context,
        repo_context=repo_context,
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
