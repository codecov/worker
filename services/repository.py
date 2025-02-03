import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple

import sentry_sdk
import shared.torngit as torngit
from asgiref.sync import async_to_sync
from shared.bots import get_adapter_auth_information
from shared.config import get_config, get_verify_ssl
from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitError,
    TorngitObjectNotFoundError,
)
from shared.typings.torngit import (
    AdditionalData,
    OwnerInfo,
    RepoInfo,
    TorngitInstanceData,
)
from shared.validation.exceptions import InvalidYamlException
from shared.yaml import UserYaml
from shared.yaml.user_yaml import OwnerContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session, lazyload

from database.enums import CommitErrorTypes
from database.models import Commit, Owner, Pull, Repository
from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from helpers.save_commit_error import save_commit_error
from helpers.token_refresh import get_token_refresh_callback
from services.yaml import read_yaml_field, save_repo_yaml_to_database_if_needed
from services.yaml.fetcher import fetch_commit_yaml_from_provider

log = logging.getLogger(__name__)

merged_pull = re.compile(r".*Merged in [^\s]+ \(pull request \#(\d+)\).*").match


@sentry_sdk.trace
def get_repo_provider_service(
    repository: Repository,
    installation_name_to_use: str = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    additional_data: AdditionalData = None,
) -> TorngitBaseAdapter:
    adapter_auth_info = get_adapter_auth_information(
        repository.owner,
        repository=repository,
        installation_name_to_use=installation_name_to_use,
    )
    if additional_data is None:
        additional_data = {}
    data = TorngitInstanceData(
        repo=RepoInfo(
            name=repository.name,
            using_integration=(
                adapter_auth_info.get("selected_installation_info") is not None
            ),
            service_id=repository.service_id,
            repoid=repository.repoid,
        ),
        owner=OwnerInfo(
            service_id=repository.owner.service_id,
            ownerid=repository.ownerid,
            username=repository.owner.username,
        ),
        installation=adapter_auth_info["selected_installation_info"],
        fallback_installations=adapter_auth_info["fallback_installations"],
        additional_data=additional_data,
    )

    adapter_params = dict(
        token=adapter_auth_info["token"],
        token_type_mapping=adapter_auth_info["token_type_mapping"],
        on_token_refresh=get_token_refresh_callback(adapter_auth_info["token_owner"]),
        **data,
    )
    return _get_repo_provider_service_instance(repository.service, adapter_params)


def _get_repo_provider_service_instance(service: str, adapter_params: dict):
    _timeouts = [
        get_config("setup", "http", "timeouts", "connect", default=30),
        get_config("setup", "http", "timeouts", "receive", default=60),
    ]
    return torngit.get(
        service,
        # Args for the Torngit instance
        timeouts=_timeouts,
        verify_ssl=get_verify_ssl(service),
        oauth_consumer_token=dict(
            key=get_config(service, "client_id"),
            secret=get_config(service, "client_secret"),
        ),
        **adapter_params,
    )


@sentry_sdk.trace
async def fetch_appropriate_parent_for_commit(
    repository_service: TorngitBaseAdapter, commit: Commit, git_commit=None
) -> str | None:
    closest_parent_without_message = None
    db_session = commit.get_db_session()
    commitid = commit.commitid
    if git_commit:
        parents = git_commit["parents"]
        possible_commit_query = db_session.query(Commit.commitid, Commit.branch).filter(
            Commit.commitid.in_(parents),
            Commit.repoid == commit.repoid,
            ~Commit.message.is_(None),
            ~Commit.deleted.is_(True),
        )
        possible_commit = _possibly_filter_out_branch(commit, possible_commit_query)
        if possible_commit:
            return possible_commit.commitid

    ancestors_tree = await repository_service.get_ancestors_tree(commitid)
    elements = [ancestors_tree]
    while elements:
        parents = [k for el in elements for k in el["parents"]]
        parent_commits = [p["commitid"] for p in parents]
        closest_parent_query = db_session.query(Commit.commitid, Commit.branch).filter(
            Commit.commitid.in_(parent_commits),
            Commit.repoid == commit.repoid,
            ~Commit.message.is_(None),
            ~Commit.deleted.is_(True),
        )
        closest_parent = _possibly_filter_out_branch(commit, closest_parent_query)
        if closest_parent:
            return closest_parent.commitid

        if closest_parent_without_message is None:
            parent_query = db_session.query(Commit.commitid, Commit.branch).filter(
                Commit.commitid.in_(parent_commits),
                Commit.repoid == commit.repoid,
                ~Commit.deleted.is_(True),
            )
            parent = _possibly_filter_out_branch(commit, parent_query)
            if parent:
                closest_parent_without_message = parent.commitid
        elements = parents

    log.warning(
        "Unable to find a parent commit that was properly found on Github",
        extra=dict(commit=commit.commitid, repoid=commit.repoid),
    )
    return closest_parent_without_message


def _possibly_filter_out_branch(commit: Commit, query: Query) -> Commit | None:
    commits = query.all()
    if len(commits) == 1:
        return commits[0]

    # if we have more than one possible commit, pick the first one with a matching `branch`:
    for possible_commit in commits:
        if possible_commit.branch == commit.branch:
            return possible_commit

    return None


def possibly_update_commit_from_provider_info(
    commit: Commit, repository_service: TorngitBaseAdapter
) -> bool:
    try:
        if not commit.message:
            log.info(
                "Commit does not have all needed info. Reaching provider to fetch info"
            )
            async_to_sync(update_commit_from_provider_info)(repository_service, commit)
            return True
    except TorngitObjectNotFoundError:
        log.warning(
            "Could not update commit with info because it was not found at the provider"
        )
        return False
    log.debug("Not updating commit because it already seems to be populated")
    return False


@sentry_sdk.trace
async def update_commit_from_provider_info(
    repository_service: TorngitBaseAdapter, commit: Commit
):
    """
    Takes the result from the torngit commit details, and updates the commit
    properties with it
    """
    db_session = commit.get_db_session()
    commitid = commit.commitid
    git_commit = await repository_service.get_commit(commitid)

    if git_commit is None:
        log.error(
            "Could not find commit on git provider",
            extra=dict(repoid=commit.repoid, commit=commit.commitid),
        )
        return

    log.debug("Found git commit", extra=dict(commit=git_commit))

    author_info = git_commit["author"]
    if not author_info.get("id"):
        commit_author = None
        log.info(
            "Not trying to set an author because it does not have an id",
            extra=dict(
                author_info=author_info,
                git_commit=git_commit,
                commit=commit.commitid,
            ),
        )
    else:
        commit_author = upsert_author(
            db_session,
            commit.repository.service,
            author_info["id"],
            author_info["username"],
            author_info["email"],
            author_info["name"],
        )

    commit.parent_commit_id = await fetch_appropriate_parent_for_commit(
        repository_service, commit, git_commit
    )
    commit.message = git_commit["message"]
    commit.author = commit_author
    commit.updatestamp = datetime.now()
    commit.timestamp = git_commit["timestamp"]

    # attempt to populate commit.pullid from repository_service if we don't have it
    if not commit.pullid:
        commit.pullid = await repository_service.find_pull_request(
            commit=commitid, branch=commit.branch
        )

    # if our records or the call above returned a pullid, fetch it's details
    if commit.pullid:
        pull_details = await repository_service.get_pull_request(pullid=commit.pullid)
        # There's a chance that the commit comes from a fork
        # so we append the branch name with the fork slug
        branch_name = pull_details["head"]["branch"]
        # TODO: 'slug' is in a `.get` because currently only GitHub returns that info
        if pull_details["head"].get("slug") != pull_details["base"].get("slug"):
            branch_name = pull_details["head"]["slug"] + ":" + branch_name
        commit.branch = branch_name
        commit.merged = False
    else:
        possible_branches = await repository_service.get_best_effort_branches(
            commit.commitid
        )
        if commit.repository.branch in possible_branches:
            commit.merged = True
            commit.branch = commit.repository.branch
        else:
            commit.merged = False

    if commit.repository.service == "bitbucket":
        res = merged_pull(git_commit["message"])
        if res:
            pullid = res.groups()[0]
            if pullid != commit.pullid:
                pull_details = await repository_service.get_pull_request(pullid)
            commit.branch = pull_details["base"]["branch"]

    db_session.flush()
    log.info(
        "Updated commit with info from git provider",
        extra=dict(
            repoid=commit.repoid,
            commit=commit.commitid,
            branch_value=commit.branch,
            author_value=commit.author_id,
        ),
    )
    db_session.commit()


def upsert_author(
    db_session, service, service_id, username, email=None, name=None
) -> Owner:
    query = db_session.query(Owner).filter(
        Owner.service == service, Owner.service_id == str(service_id)
    )
    author = query.first()

    if author:
        needs_update = False
        db_session.begin(nested=True)
        if author.username != username and username is not None:
            author.username = username
            needs_update = True
        if author.name != name and name is not None:
            author.name = name
            needs_update = True
        if author.email != email and email is not None:
            author.email = email
            needs_update = True

        if needs_update:
            db_session.commit()
        else:
            db_session.rollback()
    else:
        db_session.begin(nested=True)
        try:
            author = Owner(
                service=service,
                service_id=str(service_id),
                username=username,
                name=name,
                email=email,
                createstamp=datetime.now(),
            )
            db_session.add(author)
            db_session.commit()
        except IntegrityError:
            log.warning(
                "IntegrityError in upsert_author",
                extra=dict(service=service, service_id=service_id, username=username),
            )
            db_session.rollback()
            author = query.one()

    return author


WEBHOOK_EVENTS = {
    "github": ["pull_request", "delete", "push", "public", "status", "repository"],
    "github_enterprise": [
        "pull_request",
        "delete",
        "push",
        "public",
        "status",
        "repository",
    ],
    "bitbucket": [
        "repo:push",
        "pullrequest:created",
        "pullrequest:updated",
        "pullrequest:fulfilled",
        "repo:commit_status_created",
        "repo:commit_status_updated",
    ],
    # https://confluence.atlassian.com/bitbucketserver/post-service-webhook-for-bitbucket-server-776640367.html
    "bitbucket_server": [
        "repo:modified",
        "repo:refs_changed",
        "pr:opened",
        "pr:merged",
        "pr:declined",
        "pr:deleted",
    ],
    "gitlab": {
        "push_events": True,
        "issues_events": False,
        "merge_requests_events": True,
        "tag_push_events": False,
        "note_events": False,
        "job_events": False,
        "build_events": True,
        "pipeline_events": True,
        "wiki_events": False,
    },
    "gitlab_enterprise": {
        "push_events": True,
        "issues_events": False,
        "merge_requests_events": True,
        "tag_push_events": False,
        "note_events": False,
        "job_events": False,
        "build_events": True,
        "pipeline_events": True,
        "wiki_events": False,
    },
}


async def create_webhook_on_provider(
    repository_service, token=None, webhook_secret: Optional[str] = None
):
    """
    Posts to the provider a webhook so we can receive updates from this
    repo
    """
    webhook_url = get_config("setup", "webhook_url") or get_config(
        "setup", "codecov_url"
    )

    if webhook_secret is None:
        webhook_secret = get_config(
            repository_service.service,
            "webhook_secret",
            default="ab164bf3f7d947f2a0681b215404873e",
        )
    return await repository_service.post_webhook(
        f"Codecov Webhook. {webhook_url}",
        f"{webhook_url}/webhooks/{repository_service.service}",
        WEBHOOK_EVENTS[repository_service.service],
        webhook_secret,
        token=token,
    )


async def gitlab_webhook_update(repository_service, hookid, secret):
    """
    Edits an existing Gitlab webhook - adds a secret.
    """
    webhook_url = get_config("setup", "webhook_url") or get_config(
        "setup", "codecov_url"
    )
    return await repository_service.edit_webhook(
        hookid=hookid,
        name=f"Codecov Webhook. {webhook_url}",
        url=f"{webhook_url}/webhooks/{repository_service.service}",
        events=WEBHOOK_EVENTS[repository_service.service],
        secret=secret,
    )


def get_repo_provider_service_by_id(db_session, repoid, commitid=None):
    repo = db_session.query(Repository).filter(Repository.repoid == int(repoid)).first()

    assert repo, "repo-not-found"

    return get_repo_provider_service(repo)


@dataclass
class EnrichedPull(object):
    database_pull: Pull
    provider_pull: Optional[Mapping[str, Any]]


@sentry_sdk.trace
async def fetch_and_update_pull_request_information_from_commit(
    repository_service: TorngitBaseAdapter, commit, current_yaml
) -> Optional[EnrichedPull]:
    db_session = commit.get_db_session()
    pullid = commit.pullid
    if not commit.pullid:
        try:
            pullid = await repository_service.find_pull_request(
                commit=commit.commitid, branch=commit.branch
            )
        except TorngitClientError:
            log.warning(
                "Unable to fetch what pull request the commit belongs to",
                exc_info=True,
                extra=dict(repoid=commit.repoid, commit=commit.commitid),
            )
    if not pullid:
        return None
    enriched_pull = await fetch_and_update_pull_request_information(
        repository_service, db_session, commit.repoid, pullid, current_yaml
    )
    pull = enriched_pull.database_pull
    if pull is not None:
        head = pull.get_head_commit()
        if head is None or head.timestamp <= commit.timestamp:
            pull.head = commit.commitid
    return enriched_pull


async def _pick_best_base_comparedto_pair(
    repository_service, pull, current_yaml, pull_information
) -> Tuple[str, Optional[str]]:
    db_session = pull.get_db_session()
    repoid = pull.repoid
    candidates_to_base = (
        [pull.user_provided_base_sha, pull_information["base"]["commitid"]]
        if pull is not None and pull.user_provided_base_sha is not None
        else [pull_information["base"]["commitid"]]
    )
    for pull_base_sha in candidates_to_base:
        base_commit = (
            db_session.query(Commit)
            .filter_by(commitid=pull_base_sha, repoid=repoid)
            .first()
        )
        if base_commit:
            return (pull_base_sha, pull_base_sha)
        try:
            commit_dict = await repository_service.get_commit(pull_base_sha)
            new_base_query = db_session.query(Commit).filter(
                Commit.repoid == repoid,
                Commit.branch == pull_information["base"]["branch"],
                (Commit.pullid.is_(None) | Commit.merged),
                Commit.timestamp < commit_dict["timestamp"],
            )
            if read_yaml_field(current_yaml, ("codecov", "require_ci_to_pass"), True):
                new_base_query = new_base_query.filter(Commit.ci_passed)
            new_base_query = new_base_query.order_by(Commit.timestamp.desc())
            new_base = new_base_query.first()
            if new_base:
                return (pull_base_sha, new_base.commitid)
        except TorngitObjectNotFoundError:
            log.warning(
                "Cannot find (in the provider) commit that is supposed to be the PR base",
                extra=dict(repoid=repoid, supposed_base=pull_base_sha),
            )
    return (candidates_to_base[0], None)


@sentry_sdk.trace
async def fetch_and_update_pull_request_information(
    repository_service,
    db_session: Session,
    repoid: int | str,
    pullid: int | str,
    current_yaml,
) -> EnrichedPull:
    pull = (
        db_session.query(Pull)
        .options(lazyload("repository"))
        .filter_by(pullid=pullid, repoid=repoid)
        .first()
    )
    try:
        pull_information = await repository_service.get_pull_request(pullid=pullid)
    except TorngitClientError:
        log.warning(
            "Unable to find pull request information on provider to update it due to client error",
            extra=dict(repoid=repoid, pullid=pullid),
        )
        return EnrichedPull(database_pull=pull, provider_pull=None)
    except TorngitError:
        log.warning(
            "Unable to find pull request information on provider to update it due to unknown provider error",
            extra=dict(repoid=repoid, pullid=pullid),
        )
        return EnrichedPull(database_pull=pull, provider_pull=None)
    if not pull:
        pull = Pull(
            repoid=repoid,
            pullid=pullid,
            state=pull_information["state"],
            title=pull_information["title"],
            issueid=pull_information["id"],
        )
        db_session.add(pull)
        db_session.flush()
    else:
        pull.state = pull_information["state"]
        pull.title = pull_information["title"]
        pull.issueid = pull_information["id"]
    base_commit_sha, compared_to = await _pick_best_base_comparedto_pair(
        repository_service, pull, current_yaml, pull_information
    )
    pull.base = base_commit_sha
    pull.compared_to = compared_to

    if pull is not None and not pull.author:
        pr_author = upsert_author(
            db_session,
            repository_service.service,
            pull_information["author"]["id"],
            pull_information["author"]["username"],
        )
        if pr_author:
            pull.author = pr_author

    db_session.commit()

    return EnrichedPull(database_pull=pull, provider_pull=pull_information)


@sentry_sdk.trace
def fetch_commit_yaml_and_possibly_store(
    commit: Commit, repository_service: TorngitBaseAdapter
) -> UserYaml:
    repository = commit.repository
    try:
        log.info(
            "Fetching commit yaml from provider for commit",
            extra=dict(repoid=commit.repoid, commit=commit.commitid),
        )
        commit_yaml = async_to_sync(fetch_commit_yaml_from_provider)(
            commit, repository_service
        )
        save_repo_yaml_to_database_if_needed(commit, commit_yaml)
    except InvalidYamlException as ex:
        save_commit_error(
            commit,
            error_code=CommitErrorTypes.INVALID_YAML.value,
            error_params=dict(
                repoid=repository.repoid,
                commit=commit.commitid,
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
        commit_yaml = None
    except TorngitClientError:
        log.warning(
            "Unable to use yaml from commit because it cannot be fetched",
            extra=dict(repoid=repository.repoid, commit=commit.commitid),
            exc_info=True,
        )
        commit_yaml = None
    context = OwnerContext(
        owner_onboarding_date=repository.owner.createstamp,
        owner_plan=repository.owner.plan,
        ownerid=repository.ownerid,
    )
    return UserYaml.get_final_yaml(
        owner_yaml=repository.owner.yaml,
        repo_yaml=repository.yaml,
        commit_yaml=commit_yaml,
        owner_context=context,
    )
