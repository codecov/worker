import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

import shared.torngit as torngit
from shared.config import get_config, get_verify_ssl
from shared.encryption.oauth import get_encryptor_from_configuration
from shared.encryption.token import encode_token
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitError,
    TorngitObjectNotFoundError,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import Commit, Owner, Pull, Repository
from services.bots import get_repo_appropriate_bot_token, get_token_type_mapping
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)

merged_pull = re.compile(r".*Merged in [^\s]+ \(pull request \#(\d+)\).*").match


def get_token_refresh_callback(
    db_session: Session, ownerid: int, service: str
) -> Callable[[Dict], None]:
    """
    Produces a callback function that will encode and update the oauth token of a user.
    This callback is passed to the TorngitAdapter for the service.
    """
    if service != "gitlab" and service != "gitlab_enterprise":
        return None

    def callback(new_token: Dict) -> None:
        if "key" not in new_token and "access_token" not in new_token:
            log.error(
                "Can't save updated token. Key missing from dict",
                extra=dict(ownerid=ownerid, service=service),
            )
            return
        # shared uses a key with the token.
        # providers return access_token.
        # We can have both just in case
        new_token["access_token"] = new_token["key"]
        string_to_save = encode_token(new_token)
        encryptor = get_encryptor_from_configuration()
        oauth_token = encryptor.encode(string_to_save).decode()
        db_session.query(Owner).filter_by(ownerid=ownerid).update(
            values=dict(oauth_token=oauth_token)
        )
        db_session.commit()

    return callback


def get_repo_provider_service(
    repository, commit=None
) -> torngit.base.TorngitBaseAdapter:
    _timeouts = [
        get_config("setup", "http", "timeouts", "connect", default=30),
        get_config("setup", "http", "timeouts", "receive", default=60),
    ]
    service = repository.owner.service
    token = get_repo_appropriate_bot_token(repository)
    adapter_params = dict(
        repo=dict(
            name=repository.name,
            using_integration=repository.using_integration or False,
            service_id=repository.service_id,
            repoid=repository.repoid,
        ),
        owner=dict(
            service_id=repository.owner.service_id,
            ownerid=repository.ownerid,
            username=repository.owner.username,
        ),
        token=token,
        token_type_mapping=get_token_type_mapping(repository),
        verify_ssl=get_verify_ssl(service),
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=get_config(service, "client_id"),
            secret=get_config(service, "client_secret"),
        ),
        on_token_refresh=get_token_refresh_callback(
            repository.get_db_session(), repository.ownerid, repository.owner.service
        ),
    )
    return _get_repo_provider_service_instance(repository.service, **adapter_params)


def _get_repo_provider_service_instance(service_name, **adapter_params):
    return torngit.get(service_name, **adapter_params)


async def fetch_appropriate_parent_for_commit(
    repository_service, commit: Commit, git_commit=None
):
    closest_parent_without_message = None
    db_session = commit.get_db_session()
    commitid = commit.commitid
    if git_commit:
        parents = git_commit["parents"]
        possible_commit_query = db_session.query(Commit).filter(
            Commit.commitid.in_(parents),
            Commit.repoid == commit.repoid,
            ~Commit.message.is_(None),
            ~Commit.deleted.is_(True),
        )
        possible_commit = possible_commit_query.first()
        if possible_commit:
            return possible_commit.commitid
    ancestors_tree = await repository_service.get_ancestors_tree(commitid)
    elements = [ancestors_tree]
    while elements:
        parents = [k for el in elements for k in el["parents"]]
        parent_commits = [p["commitid"] for p in parents]
        closest_parent = (
            db_session.query(Commit)
            .filter(
                Commit.commitid.in_(parent_commits),
                Commit.repoid == commit.repoid,
                ~Commit.message.is_(None),
                ~Commit.deleted.is_(True),
            )
            .first()
        )
        if closest_parent:
            return closest_parent.commitid
        if closest_parent_without_message is None:
            res = (
                db_session.query(Commit.commitid)
                .filter(
                    Commit.commitid.in_(parent_commits),
                    Commit.repoid == commit.repoid,
                    ~Commit.deleted.is_(True),
                )
                .first()
            )
            if res:
                closest_parent_without_message = res[0]
        elements = parents
    log.warning(
        "Unable to find a parent commit that was properly found on Github",
        extra=dict(commit=commit.commitid, repoid=commit.repoid),
    )
    return closest_parent_without_message


async def update_commit_from_provider_info(repository_service, commit):
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
    else:
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
            commit_author = get_or_create_author(
                db_session,
                commit.repository.service,
                author_info["id"],
                author_info["username"],
                author_info["email"],
                author_info["name"],
            )

        # attempt to populate commit.pullid from repository_service if we don't have it
        if not commit.pullid:
            commit.pullid = await repository_service.find_pull_request(
                commit=commitid, branch=commit.branch
            )

        # if our records or the call above returned a pullid, fetch it's details
        if commit.pullid:
            commit_updates = await repository_service.get_pull_request(
                pullid=commit.pullid
            )
            commit.branch = commit_updates["head"]["branch"]
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
        commit.message = git_commit["message"]
        commit.parent_commit_id = await fetch_appropriate_parent_for_commit(
            repository_service, commit, git_commit
        )
        commit.author = commit_author
        commit.updatestamp = datetime.now()
        commit.timestamp = git_commit["timestamp"]

        if commit.repository.service == "bitbucket":
            res = merged_pull(git_commit["message"])
            if res:
                pullid = res.groups()[0]
                pullid = pullid
                commit.branch = (await repository_service.get_pull_request(pullid))[
                    "base"
                ]["branch"]
        log.info(
            "Updated commit with info from git provider",
            extra=dict(
                repoid=commit.repoid,
                commit=commit.commitid,
                branch_value=commit.branch,
                author_value=commit.author_id,
            ),
        )


def get_or_create_author(
    db_session, service, service_id, username, email=None, name=None
) -> Owner:
    query = db_session.query(Owner).filter(
        Owner.service == service, Owner.service_id == str(service_id)
    )
    author = query.first()
    if author:
        return author

    db_session.begin(nested=True)
    try:
        author = Owner(
            service=service,
            service_id=str(service_id),
            username=username,
            name=name,
            email=email,
        )
        db_session.add(author)
        db_session.commit()
        return author
    except IntegrityError:
        log.warning(
            "IntegrityError in get_or_create_author",
            extra=dict(service=service, service_id=service_id, username=username),
        )
        db_session.rollback()
        author = query.one()
        return author


async def create_webhook_on_provider(repository_service, token=None):
    """
    Posts to the provider a webhook so we can receive updates from this
    repo
    """
    webhook_url = get_config("setup", "webhook_url") or get_config(
        "setup", "codecov_url"
    )
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
    return await repository_service.post_webhook(
        f"Codecov Webhook. {webhook_url}",
        f"{webhook_url}/webhooks/{repository_service.service}",
        WEBHOOK_EVENTS[repository_service.service],
        get_config(
            repository_service.service,
            "webhook_secret",
            default="ab164bf3f7d947f2a0681b215404873e",
        ),
        token=token,
    )


def get_repo_provider_service_by_id(db_session, repoid, commitid=None):
    repo = db_session.query(Repository).filter(Repository.repoid == int(repoid)).first()

    assert repo, "repo-not-found"

    return get_repo_provider_service(repo)


@dataclass
class EnrichedPull(object):
    database_pull: Pull
    provider_pull: Optional[Mapping[str, Any]]


async def fetch_and_update_pull_request_information_from_commit(
    repository_service, commit, current_yaml
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


async def fetch_and_update_pull_request_information(
    repository_service, db_session, repoid, pullid, current_yaml
) -> EnrichedPull:
    try:
        pull_information = await repository_service.get_pull_request(pullid=pullid)
    except TorngitClientError:
        log.warning(
            "Unable to find pull request information on provider to update it due to client error",
            extra=dict(repoid=repoid, pullid=pullid),
        )
        pull = db_session.query(Pull).filter_by(pullid=pullid, repoid=repoid).first()
        return EnrichedPull(database_pull=pull, provider_pull=None)
    except TorngitError:
        log.warning(
            "Unable to find pull request information on provider to update it due to unknown provider error",
            extra=dict(repoid=repoid, pullid=pullid),
        )
        pull = db_session.query(Pull).filter_by(pullid=pullid, repoid=repoid).first()
        return EnrichedPull(database_pull=pull, provider_pull=None)
    db_session.flush()
    command = (
        insert(Pull.__table__)
        .values(
            pullid=pullid,
            repoid=repoid,
            issueid=pull_information["id"],
            state=pull_information["state"],
            title=pull_information["title"],
        )
        .on_conflict_do_update(
            index_elements=[Pull.repoid, Pull.pullid],
            set_=dict(
                issueid=pull_information["id"],
                state=pull_information["state"],
                title=pull_information["title"],
            ),
        )
    )
    db_session.connection().execute(command)
    db_session.flush()
    pull = db_session.query(Pull).filter_by(pullid=pullid, repoid=repoid).first()
    db_session.refresh(pull)
    base_commit_sha, compared_to = await _pick_best_base_comparedto_pair(
        repository_service, pull, current_yaml, pull_information
    )
    pull.base = base_commit_sha
    pull.compared_to = compared_to

    if pull is not None and not pull.author:
        pr_author = get_or_create_author(
            db_session,
            repository_service.service,
            pull_information["author"]["id"],
            pull_information["author"]["username"],
        )
        if pr_author:
            pull.author = pr_author

    return EnrichedPull(database_pull=pull, provider_pull=pull_information)
