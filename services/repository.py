import logging
from datetime import datetime
import re
from typing import Mapping, Any
from dataclasses import dataclass

import torngit
from torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import FlushError

from covreports.config import get_config, get_verify_ssl
from services.bots import get_repo_appropriate_bot_token
from database.models import Owner, Commit, Pull, Repository
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)

merged_pull = re.compile(r".*Merged in [^\s]+ \(pull request \#(\d+)\).*").match


def get_repo_provider_service(repository, commit=None) -> torngit.base.BaseHandler:
    _timeouts = [
        get_config("setup", "http", "timeouts", "connect", default=15),
        get_config("setup", "http", "timeouts", "receive", default=30),
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
        verify_ssl=get_verify_ssl(service),
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=get_config(service, "client_id"),
            secret=get_config(service, "client_secret"),
        ),
    )
    return _get_repo_provider_service_instance(repository.service, **adapter_params)


def _get_repo_provider_service_instance(service_name, **adapter_params):
    return torngit.get(service_name, **adapter_params)


async def fetch_appropriate_parent_for_commit(
    repository_service, commit: Commit, git_commit=None
):
    db_session = commit.get_db_session()
    commitid = commit.commitid
    if git_commit:
        parents = git_commit["parents"]
        possible_commit_query = db_session.query(Commit).filter(
            Commit.commitid.in_(parents), Commit.repoid == commit.repoid
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
            .filter(Commit.commitid.in_(parent_commits), Commit.repoid == commit.repoid)
            .first()
        )
        if closest_parent:
            return closest_parent.commitid
        elements = parents
    return None


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
            commit_author = get_author_from_commit(
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

        commit.message = git_commit["message"]
        commit.parent_commit_id = await fetch_appropriate_parent_for_commit(
            repository_service, commit, git_commit
        )
        commit.merged = False
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
            extra=dict(repoid=commit.repoid, commit=commit.commitid),
        )


def get_author_from_commit(db_session, service, author_id, username, email, name):
    author = (
        db_session.query(Owner)
        .filter_by(service_id=str(author_id), service=service)
        .first()
    )
    if author:
        return author
    author = Owner(
        service_id=str(author_id),
        service=service,
        username=username,
        name=name,
        email=email,
    )
    db_session.add(author)
    return author


async def create_webhook_on_provider(repository_service):
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
        "bitbucket_server": [],
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
    )


def get_repo_provider_service_by_id(db_session, repoid, commitid=None):
    repo = db_session.query(Repository).filter(Repository.repoid == int(repoid)).first()

    assert repo, "repo-not-found"

    return get_repo_provider_service(repo)


@dataclass
class EnrichedPull(object):
    database_pull: Pull
    provider_pull: Mapping[str, Any]


async def fetch_and_update_pull_request_information_from_commit(
    repository_service, commit, current_yaml
) -> EnrichedPull:
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
        pull.author = commit.author # TODO: remove in favor of author from torngit response?
        pull.head = commit.commitid
    return enriched_pull


async def fetch_and_update_pull_request_information(
    repository_service, db_session, repoid, pullid, current_yaml
) -> EnrichedPull:
    compared_to = None
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
    pull_base_sha = pull_information["base"]["commitid"]
    base_commit = (
        db_session.query(Commit)
        .filter_by(commitid=pull_base_sha, repoid=repoid)
        .first()
    )
    if base_commit:
        compared_to = base_commit.commitid
    else:
        try:
            commit_dict = await repository_service.get_commit(
                pull_information["base"]["commitid"]
            )
            new_base_query = db_session.query(Commit).filter(
                Commit.repoid == repoid,
                Commit.branch == pull_information["base"]["branch"],
                (Commit.pullid.is_(None) | Commit.merged),
                Commit.timestamp < commit_dict["timestamp"],
            )
            if read_yaml_field(current_yaml, ("codecov", "require_ci_to_pass"), True):
                new_base_query = new_base_query.filter(Commit.ci_passed)
            new_base_query.order_by(Commit.timestamp.desc())
            new_base = new_base_query.first()
            if new_base:
                compared_to = new_base.commitid
        except TorngitObjectNotFoundError:
            log.warning(
                "Cannot find (in the provider) commit that is supposed to be the PR base",
                extra=dict(
                    repoid=repoid,
                    pullid=pullid,
                    supposed_base=pull_information["base"]["commitid"],
                ),
            )
    db_session.flush()
    db_session.begin_nested()
    pull = Pull(
        pullid=pullid,
        repoid=repoid,
        issueid=pull_information["id"],
        state=pull_information["state"],
        title=pull_information["title"],
        base=pull_information["base"]["commitid"],
        compared_to=compared_to,
    )
    db_session.add(pull)
    try:
        db_session.flush()
    except (IntegrityError, FlushError):
        db_session.rollback()
        log.info(
            "The pull is already in the database now. We will only fetch it then",
            extra=dict(repoid=repoid, pullid=pullid),
        )
        pull_query = db_session.query(Pull).filter_by(pullid=pullid, repoid=repoid)
        pull = pull_query.first()
        pull.issueid = pull_information["id"]
        pull.state = pull_information["state"]
        pull.title = pull_information["title"]
        pull.base = pull_information["base"]["commitid"]
        pull.compared_to = compared_to
        db_session.flush()
        log.info(
            "Fetched and updated existing pull",
            extra=dict(repoid=repoid, pullid=pullid),
        )
    else:
        db_session.commit()
    return EnrichedPull(database_pull=pull, provider_pull=pull_information)
